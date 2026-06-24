"""Unit tests for the reasoning-cache store (Phase 4 read / Phase 5 write).

Deterministic, no Postgres, no LLM. A fake async DB returns canned result sets
(the SQLAlchemy WHERE clauses are not evaluated — we assert the store's logic:
normalization, hashing, read-only gating, flag gating, upsert-vs-insert, fuzzy
recall ordering, and context rendering).

Covers:
 - normalize_question / question_hash determinism
 - is_read_only accepts SELECT/WITH, rejects writes + multi-statement + write tokens
 - capture is a no-op when HYBRID_QUERY_CACHE is off
 - capture inserts a pending row (and is skipped for non-read-only SQL)
 - capture bumps an existing row instead of duplicating
 - recall is a no-op when HYBRID_BRAIN_READ is off
 - recall returns exact-hash first, then fuzzy >= floor, capped at limit
 - render_proven_queries produces a PROVEN QUERIES block (empty -> '')
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.ai.brain import query_cache_store as store


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeDB:
    """Returns a queued result per execute(); records add/commit/rollback."""

    def __init__(self, results):
        self._results = list(results)
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        return self._results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _row(question_norm, sql, qhash=None, hit_count=0, status="active"):
    return SimpleNamespace(
        id="row-" + question_norm[:8],
        question_norm=question_norm,
        question_hash=qhash or store.question_hash(question_norm),
        sql_text=sql,
        hit_count=hit_count,
        status=status,
    )


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_normalize_question_deterministic():
    assert store.normalize_question("  Show  Top 10 Stores? ") == "show top 10 stores"
    assert store.normalize_question("Revenue by Month.") == "revenue by month"
    # idempotent
    n = store.normalize_question("HELLO   World!!")
    assert store.normalize_question(n) == n


def test_question_hash_stable_and_case_insensitive_via_norm():
    a = store.question_hash(store.normalize_question("Top Stores"))
    b = store.question_hash(store.normalize_question("  top stores  "))
    assert a == b
    assert len(a) == 64


@pytest.mark.parametrize(
    "sql,ok",
    [
        ("SELECT 1", True),
        ("  select * from sales ", True),
        ("WITH t AS (SELECT 1) SELECT * FROM t", True),
        ("SELECT created_at FROM orders", True),  # 'create' inside identifier must not trip
        ("INSERT INTO x VALUES (1)", False),
        ("UPDATE x SET a=1", False),
        ("DROP TABLE x", False),
        ("SELECT 1; DELETE FROM x", False),  # multi-statement
        ("SELECT 1; SELECT 2", False),
        ("", False),
    ],
)
def test_is_read_only(sql, ok):
    assert store.is_read_only(sql) is ok


def test_render_proven_queries():
    assert store.render_proven_queries([]) == ""
    block = store.render_proven_queries([{"question": "top stores", "sql": "SELECT 1"}])
    assert "PROVEN QUERIES" in block
    assert "top stores" in block
    assert "```sql" in block and "SELECT 1" in block


# --------------------------------------------------------------------------- #
# capture (Phase 5 write)
# --------------------------------------------------------------------------- #
def test_capture_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("HYBRID_QUERY_CACHE", raising=False)
    db = _FakeDB([])
    rid = _run(store.capture_query(
        db, organization_id="org1", data_source_id=None,
        question="top stores", sql="SELECT 1",
    ))
    assert rid is None
    assert db.added == []


def test_capture_skips_non_read_only(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    db = _FakeDB([])
    rid = _run(store.capture_query(
        db, organization_id="org1", data_source_id=None,
        question="wipe it", sql="DELETE FROM sales",
    ))
    assert rid is None
    assert db.added == []


def test_capture_inserts_pending_row(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    db = _FakeDB([_FakeResult([])])  # no existing row
    rid = _run(store.capture_query(
        db, organization_id="org1", data_source_id="ds1",
        question="Top 10 stores?", sql="SELECT name FROM stores LIMIT 10",
    ))
    assert rid is not None
    assert len(db.added) == 1
    row = db.added[0]
    assert row.status == "pending"
    assert row.question_norm == "top 10 stores"
    assert row.organization_id == "org1"
    assert row.hit_count == 1
    assert db.commits == 1


def test_capture_bumps_existing(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    existing = _row("top 10 stores", "SELECT name FROM stores LIMIT 10", hit_count=2, status="active")
    db = _FakeDB([_FakeResult([existing])])
    rid = _run(store.capture_query(
        db, organization_id="org1", data_source_id="ds1",
        question="Top 10 stores", sql="SELECT name FROM stores LIMIT 10 -- v2",
    ))
    assert rid == existing.id
    assert db.added == []            # no duplicate insert
    assert existing.hit_count == 3   # bumped
    assert existing.sql_text.endswith("-- v2")  # latest proven SQL kept
    assert db.commits == 1


# --------------------------------------------------------------------------- #
# recall (Phase 4 read)
# --------------------------------------------------------------------------- #
def test_recall_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("HYBRID_BRAIN_READ", raising=False)
    db = _FakeDB([_FakeResult([_row("top stores", "SELECT 1")])])
    out = _run(store.recall_proven_queries(
        db, organization_id="org1", data_source_id="ds1", question="top stores",
    ))
    assert out == []


def test_recall_exact_then_fuzzy_capped(monkeypatch):
    monkeypatch.setenv("HYBRID_BRAIN_READ", "1")
    rows = [
        _row("revenue by month", "SELECT a"),                      # fuzzy-ish
        _row("top 10 stores by revenue", "SELECT b"),              # exact target
        _row("top 10 stores revenue ranking", "SELECT c"),         # fuzzy match (Jaccard 0.8 >= floor)
        _row("totally unrelated weather data", "SELECT d"),        # below floor
    ]
    db = _FakeDB([_FakeResult(rows)])
    out = _run(store.recall_proven_queries(
        db, organization_id="org1", data_source_id="ds1",
        question="top 10 stores by revenue", limit=2,
    ))
    assert len(out) == 2
    assert out[0]["sql"] == "SELECT b"           # exact hash match ranks first
    assert all(o["sql"] != "SELECT d" for o in out)  # unrelated excluded
