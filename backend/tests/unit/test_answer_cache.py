"""Unit tests for the Tier-1 answer-cache store (app.ai.brain.answer_cache).

Deterministic, no Postgres driver, no LLM, no app conftest fixtures. Runs under
``--noconftest`` and on Python 3.9 (no ``X | None`` syntax — Optional only; async
coroutines driven via ``asyncio.run(...)`` inside sync test functions, so we do
not depend on the pytest-asyncio plugin being configured — same pattern as the
other brain/concurrency unit tests).

The store awaits ``db.execute/commit/rollback`` and calls ``db.add`` on an async
session. We back it with a real *sync* SQLAlchemy Session over an in-memory
SQLite DB, wrapped in a tiny async shim, so the ORM filtering (hash/scope/expiry)
is exercised for real without needing an async sqlite driver (aiosqlite is not
installed locally).
"""

from __future__ import annotations

import asyncio

import pytest

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session, configure_mappers

    from app.models.base import Base, BaseSchema

    # Register lightweight relationship targets so AnswerCache's mapper can
    # resolve relationship("Organization"/"DataSource") without importing the
    # heavy real models (which pull optional deps like fastapi_mail).
    if "Organization" not in Base.registry._class_registry:
        class Organization(BaseSchema):  # noqa: D401 - stub
            __tablename__ = "organizations"

    if "DataSource" not in Base.registry._class_registry:
        class DataSource(BaseSchema):  # noqa: D401 - stub
            __tablename__ = "data_sources"

    from app.models.answer_cache import AnswerCache
    from app.ai.brain.answer_cache import serve_answer_cache, store_answer
    from app.ai.brain.query_cache_store import normalize_question, question_hash

    configure_mappers()
    _IMPORT_OK = True
except Exception as _exc:  # pragma: no cover - environment guard
    _IMPORT_OK = False
    _IMPORT_ERR = _exc

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="answer_cache import failed (likely py-version/dep): {0}".format(
        _IMPORT_ERR if not _IMPORT_OK else ""
    ),
)


# Plain DDL (no FK enforcement) so we don't need the referenced tables to exist.
_DDL = """
CREATE TABLE answer_cache (
  id VARCHAR(36) PRIMARY KEY,
  organization_id VARCHAR(36) NOT NULL,
  data_source_id VARCHAR(36),
  question_norm TEXT NOT NULL,
  question_hash VARCHAR(64) NOT NULL,
  answer_md TEXT NOT NULL,
  row_count INTEGER NOT NULL DEFAULT 0,
  sql_text TEXT,
  hit_count INTEGER NOT NULL DEFAULT 0,
  last_used_at DATETIME,
  expires_at DATETIME,
  created_at DATETIME,
  updated_at DATETIME,
  deleted_at DATETIME
)
"""


class _AsyncSession:
    """Async shim over a sync SQLAlchemy Session.

    The store awaits execute/commit/rollback and calls .add synchronously.
    """

    def __init__(self, sync_session):
        self._s = sync_session

    async def execute(self, stmt):
        return self._s.execute(stmt)

    async def commit(self):
        self._s.commit()

    async def rollback(self):
        self._s.rollback()

    def add(self, obj):
        self._s.add(obj)


def _make_db():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text(_DDL))
    return _AsyncSession(Session(eng))


def _run(coro):
    return asyncio.run(coro)


def _enable(monkeypatch, on=True):
    import app.settings.hybrid_flags as hf

    monkeypatch.setattr(type(hf.flags), "ANSWER_CACHE", property(lambda self: on))


# ---------------------------------------------------------------------------
# Pure helpers (reused from query_cache_store)
# ---------------------------------------------------------------------------

def test_normalize_question_is_deterministic():
    assert normalize_question("  Show ME Sales?? ") == "show me sales"
    assert normalize_question("Foo  Bar") == "foo bar"
    assert normalize_question("") == ""


def test_question_hash_matches_normalized_form():
    a = question_hash(normalize_question("Total revenue?"))
    b = question_hash(normalize_question("  total revenue "))
    assert a == b
    assert len(a) == 64  # sha-256 hex


# ---------------------------------------------------------------------------
# Flag-off => total no-op
# ---------------------------------------------------------------------------

def test_serve_flag_off_is_noop(monkeypatch):
    _enable(monkeypatch, on=False)
    db = _make_db()
    out = _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="hi"))
    assert out is None


def test_store_flag_off_is_noop(monkeypatch):
    _enable(monkeypatch, on=False)
    db = _make_db()
    rid = _run(store_answer(db, organization_id="o1", data_source_id=None, question="hi", answer_md="A"))
    assert rid is None


# ---------------------------------------------------------------------------
# Guard rails (flag on, but bad inputs) => None, no raise
# ---------------------------------------------------------------------------

def test_serve_guards_return_none(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    assert _run(serve_answer_cache(None, organization_id="o1", data_source_id=None, question="hi")) is None
    assert _run(serve_answer_cache(db, organization_id="", data_source_id=None, question="hi")) is None
    assert _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="")) is None


def test_store_guards_return_none(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    assert _run(store_answer(db, organization_id="o1", data_source_id=None, question="", answer_md="A")) is None
    assert _run(store_answer(db, organization_id="o1", data_source_id=None, question="q", answer_md="")) is None


# ---------------------------------------------------------------------------
# Round-trip store -> serve
# ---------------------------------------------------------------------------

def test_store_then_serve_roundtrips(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    rid = _run(store_answer(
        db, organization_id="o1", data_source_id="ds1",
        question="Top products?", answer_md="### Top\n- A", row_count=5, sql_text="SELECT 1",
    ))
    assert rid is not None

    out = _run(serve_answer_cache(db, organization_id="o1", data_source_id="ds1", question="  top products "))
    assert out is not None
    answer_md, row_count = out
    assert answer_md == "### Top\n- A"
    assert row_count == 5


def test_serve_miss_returns_none(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    _run(store_answer(db, organization_id="o1", data_source_id=None, question="known", answer_md="A"))
    # Different question -> different hash -> miss.
    assert _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="unknown")) is None


def test_scope_mismatch_does_not_serve(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    # Stored org-wide (data_source NULL); a scoped serve for ds1 must not match.
    _run(store_answer(db, organization_id="o1", data_source_id=None, question="q", answer_md="A"))
    assert _run(serve_answer_cache(db, organization_id="o1", data_source_id="ds1", question="q")) is None
    # And the org-wide serve does match.
    assert _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="q")) is not None


# ---------------------------------------------------------------------------
# Hit-count bump
# ---------------------------------------------------------------------------

def test_serve_bumps_hit_count(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    rid = _run(store_answer(db, organization_id="o1", data_source_id=None, question="q", answer_md="A"))
    # Stored row starts at hit_count=1; two serves -> 3.
    _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="q"))
    _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="q"))

    row = db._s.get(AnswerCache, rid)
    assert row.hit_count == 3
    assert row.last_used_at is not None


# ---------------------------------------------------------------------------
# TTL / expiry
# ---------------------------------------------------------------------------

def test_expired_row_not_served(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    rid = _run(store_answer(
        db, organization_id="o1", data_source_id=None, question="q", answer_md="A",
        ttl_seconds=-5,  # already expired
    ))
    assert rid is not None
    assert _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="q")) is None


def test_fresh_ttl_is_served(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    _run(store_answer(
        db, organization_id="o1", data_source_id=None, question="q", answer_md="A",
        ttl_seconds=3600,
    ))
    out = _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="q"))
    assert out is not None and out[0] == "A"


# ---------------------------------------------------------------------------
# Upsert refresh (no duplicate rows)
# ---------------------------------------------------------------------------

def test_store_upserts_same_key(monkeypatch):
    _enable(monkeypatch, on=True)
    db = _make_db()
    rid1 = _run(store_answer(db, organization_id="o1", data_source_id=None, question="q", answer_md="old", row_count=1))
    rid2 = _run(store_answer(db, organization_id="o1", data_source_id=None, question="q", answer_md="new", row_count=9))
    assert rid1 == rid2  # same row refreshed, not duplicated

    out = _run(serve_answer_cache(db, organization_id="o1", data_source_id=None, question="q"))
    assert out == ("new", 9)

    count = db._s.query(AnswerCache).count()
    assert count == 1


# ---------------------------------------------------------------------------
# Error swallowing => None (never raises into caller)
# ---------------------------------------------------------------------------

class _BoomSession:
    async def execute(self, *_a, **_k):
        raise RuntimeError("boom")

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def add(self, *_a, **_k):
        pass


def test_serve_swallows_db_error(monkeypatch):
    _enable(monkeypatch, on=True)
    assert _run(serve_answer_cache(_BoomSession(), organization_id="o1", data_source_id=None, question="q")) is None


def test_store_swallows_db_error(monkeypatch):
    _enable(monkeypatch, on=True)
    assert _run(store_answer(_BoomSession(), organization_id="o1", data_source_id=None, question="q", answer_md="A")) is None
