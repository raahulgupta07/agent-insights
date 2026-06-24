"""Unit tests for the reasoning-cache CURATOR (Phase 5 promote).

Deterministic, no Postgres, no LLM. A fake async DB returns a canned result set
(the SQLAlchemy WHERE clauses are NOT evaluated here — we pre-filter the canned
rows to mirror what the query would return, and assert the curator's promotion
logic: flag gating, mutate vs. dry_run, source/status flip, and candidate ids).

Covers:
 - promote is a no-op (zeros) when HYBRID_QUERY_CACHE is off
 - only rows meeting the rule (already pre-filtered by the fake query) get
   flipped pending->active, and their ids are returned as candidates
 - dry_run promotes nothing (no commit, no status change) but lists candidates
 - empty candidate set -> {'promoted': 0, 'candidates': []}
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.ai.brain import query_cache_curator as curator


# --------------------------------------------------------------------------- #
# Fakes (mirror tests/unit/test_query_cache_store.py)
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    """Returns a queued result per execute(); records commit/rollback."""

    def __init__(self, results):
        self._results = list(results)
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        return self._results.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _row(rid, *, hit_count, thumbs_down=0, status="pending", source="chat"):
    return SimpleNamespace(
        id=rid,
        hit_count=hit_count,
        thumbs_down=thumbs_down,
        status=status,
        source=source,
        last_used_at=None,
    )


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Flag gating
# --------------------------------------------------------------------------- #
def test_promote_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("HYBRID_QUERY_CACHE", raising=False)
    # An execute here would IndexError on the empty queue if the flag gate
    # didn't short-circuit first — so this also proves no DB work happens.
    db = _FakeDB([])
    out = _run(curator.promote_proven_queries(db))
    assert out == {"promoted": 0, "candidates": []}
    assert db.commits == 0


def test_promote_noop_when_db_none(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    out = _run(curator.promote_proven_queries(None))
    assert out == {"promoted": 0, "candidates": []}


# --------------------------------------------------------------------------- #
# Promotion
# --------------------------------------------------------------------------- #
def test_promote_flips_qualifying_rows(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    # The real WHERE filters to hit_count>=floor AND thumbs_down==0; the fake DB
    # can't run SQL, so the canned set already reflects that filter.
    qualifying = [
        _row("a", hit_count=3),
        _row("b", hit_count=10),
    ]
    db = _FakeDB([_FakeResult(qualifying)])
    out = _run(curator.promote_proven_queries(db, min_hits=3))
    assert out["promoted"] == 2
    assert sorted(out["candidates"]) == ["a", "b"]
    assert all(r.status == "active" for r in qualifying)
    assert all(r.source == "curator" for r in qualifying)
    assert db.commits == 1


def test_promote_empty_candidate_set(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    db = _FakeDB([_FakeResult([])])
    out = _run(curator.promote_proven_queries(db, min_hits=3))
    assert out == {"promoted": 0, "candidates": []}
    assert db.commits == 0  # nothing to commit


def test_dry_run_lists_but_promotes_nothing(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    rows = [
        _row("x", hit_count=5),
        _row("y", hit_count=99),
    ]
    db = _FakeDB([_FakeResult(rows)])
    out = _run(curator.promote_proven_queries(db, min_hits=3, dry_run=True))
    assert out["promoted"] == 0
    assert sorted(out["candidates"]) == ["x", "y"]
    # dry_run must not mutate or commit.
    assert all(r.status == "pending" for r in rows)
    assert all(r.source == "chat" for r in rows)
    assert db.commits == 0


def test_env_overrides_min_hits(monkeypatch):
    """QUERY_CURATOR_MIN_HITS env overrides the arg-supplied floor.

    The fake DB can't apply the WHERE, but we can prove the env is read by
    confirming the effective-floor helper picks it up.
    """
    monkeypatch.setenv("QUERY_CURATOR_MIN_HITS", "7")
    assert curator._env_min_hits(3) == 7
    monkeypatch.setenv("QUERY_CURATOR_MIN_HITS", "not-an-int")
    assert curator._env_min_hits(3) == 3  # bad value falls back to default
    monkeypatch.delenv("QUERY_CURATOR_MIN_HITS", raising=False)
    assert curator._env_min_hits(5) == 5
