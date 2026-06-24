"""Unit tests for the reasoning-cache serve path (Phase 4 zero-LLM serve).

Deterministic, no Postgres, no LLM. `recall_proven_queries` is monkeypatched
with an async fake so the serve logic is tested in isolation from the store's
DB/normalization internals. `run_sql` is a sync callable returning a real
pandas DataFrame (a project dep).

Covers:
 - serve is a no-op (None) unless BOTH HYBRID_QUERY_CACHE and HYBRID_BRAIN_READ
 - serve is a no-op when recall returns nothing
 - serve is a no-op (and never runs SQL) when the top recall != exact question
 - serve runs the proven SQL once and returns a ServeResult on exact match
 - serve refuses non-read-only proven SQL (None, no run_sql)
 - serve swallows a run_sql exception (None, no propagation)
 - serve caps rows at MAX_SERVE_ROWS and flags truncated
 - render_answer_markdown: table headers + cell + ```sql fence; truncation
   "first N of M" line; empty-rows renders gracefully; pipe in a cell escaped
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from app.ai.brain import query_cache_serve as serve
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
    """A stand-in async DB; serve never touches it because recall is faked."""

    def __init__(self, results=None):
        self._results = list(results or [])
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


class _RunSpy:
    """Sync callable(sql) -> DataFrame; records calls (or raises)."""

    def __init__(self, df=None, raises=None):
        self._df = df
        self._raises = raises
        self.calls = []

    def __call__(self, sql):
        self.calls.append(sql)
        if self._raises is not None:
            raise self._raises
        return self._df


def _patch_recall(monkeypatch, items):
    """Replace recall_proven_queries with an async fake returning `items`."""

    async def _fake_recall(db, **kwargs):
        return list(items)

    monkeypatch.setattr(serve, "recall_proven_queries", _fake_recall)


def _both_flags_on(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    monkeypatch.setenv("HYBRID_BRAIN_READ", "1")


def _serve(db, question, run_sql):
    return asyncio.run(
        serve.try_serve_proven_query(
            db,
            organization_id="org1",
            data_source_id="ds1",
            question=question,
            run_sql=run_sql,
        )
    )


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Flag gating
# --------------------------------------------------------------------------- #
def test_serve_noop_when_both_flags_off(monkeypatch):
    monkeypatch.delenv("HYBRID_QUERY_CACHE", raising=False)
    monkeypatch.delenv("HYBRID_BRAIN_READ", raising=False)
    _patch_recall(monkeypatch, [{"question": "top stores", "sql": "SELECT 1"}])
    run = _RunSpy(df=pd.DataFrame({"a": [1]}))
    assert _serve(_FakeDB(), "top stores", run) is None
    assert run.calls == []


def test_serve_noop_when_only_query_cache_on(monkeypatch):
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    monkeypatch.delenv("HYBRID_BRAIN_READ", raising=False)
    _patch_recall(monkeypatch, [{"question": "top stores", "sql": "SELECT 1"}])
    run = _RunSpy(df=pd.DataFrame({"a": [1]}))
    assert _serve(_FakeDB(), "top stores", run) is None
    assert run.calls == []


def test_serve_noop_when_only_brain_read_on(monkeypatch):
    monkeypatch.delenv("HYBRID_QUERY_CACHE", raising=False)
    monkeypatch.setenv("HYBRID_BRAIN_READ", "1")
    _patch_recall(monkeypatch, [{"question": "top stores", "sql": "SELECT 1"}])
    run = _RunSpy(df=pd.DataFrame({"a": [1]}))
    assert _serve(_FakeDB(), "top stores", run) is None
    assert run.calls == []


# --------------------------------------------------------------------------- #
# Recall gating / exact-match-only
# --------------------------------------------------------------------------- #
def test_serve_noop_when_recall_empty(monkeypatch):
    _both_flags_on(monkeypatch)
    _patch_recall(monkeypatch, [])
    run = _RunSpy(df=pd.DataFrame({"a": [1]}))
    assert _serve(_FakeDB(), "top stores", run) is None
    assert run.calls == []


def test_serve_noop_when_top_is_only_fuzzy(monkeypatch):
    _both_flags_on(monkeypatch)
    # recall surfaced a related-but-not-identical question -> serve must decline.
    _patch_recall(
        monkeypatch,
        [{"question": store.normalize_question("top 5 stores by revenue"),
          "sql": "SELECT 1"}],
    )
    run = _RunSpy(df=pd.DataFrame({"a": [1]}))
    assert _serve(_FakeDB(), "top 10 stores by revenue", run) is None
    assert run.calls == []


# --------------------------------------------------------------------------- #
# Exact match serve
# --------------------------------------------------------------------------- #
def test_serve_exact_match_runs_sql_once(monkeypatch):
    _both_flags_on(monkeypatch)
    question = "Top 10 Stores?"
    proven_sql = "SELECT name, revenue FROM stores ORDER BY revenue DESC LIMIT 10"
    _patch_recall(
        monkeypatch,
        [{"question": store.normalize_question(question), "sql": proven_sql}],
    )
    df = pd.DataFrame({"name": ["A", "B"], "revenue": [100, 90]})
    run = _RunSpy(df=df)

    res = _serve(_FakeDB(), question, run)

    assert res is not None
    assert run.calls == [proven_sql]
    assert res.sql == proven_sql
    assert res.columns == ["name", "revenue"]
    assert res.rows == [["A", 100], ["B", 90]]
    assert res.row_count == 2
    assert res.truncated is False


def test_serve_refuses_non_read_only_sql(monkeypatch):
    _both_flags_on(monkeypatch)
    question = "wipe stores"
    _patch_recall(
        monkeypatch,
        [{"question": store.normalize_question(question), "sql": "DELETE FROM stores"}],
    )
    run = _RunSpy(df=pd.DataFrame({"a": [1]}))
    assert _serve(_FakeDB(), question, run) is None
    assert run.calls == []


def test_serve_swallows_run_sql_exception(monkeypatch):
    _both_flags_on(monkeypatch)
    question = "top stores"
    _patch_recall(
        monkeypatch,
        [{"question": store.normalize_question(question), "sql": "SELECT 1"}],
    )
    run = _RunSpy(raises=RuntimeError("warehouse down"))
    # exception must NOT propagate; serve degrades to None.
    assert _serve(_FakeDB(), question, run) is None
    assert run.calls == ["SELECT 1"]  # it tried, then swallowed


# --------------------------------------------------------------------------- #
# Row cap
# --------------------------------------------------------------------------- #
def test_serve_caps_rows_and_flags_truncated(monkeypatch):
    _both_flags_on(monkeypatch)
    question = "all stores"
    _patch_recall(
        monkeypatch,
        [{"question": store.normalize_question(question), "sql": "SELECT id FROM stores"}],
    )
    total = serve.MAX_SERVE_ROWS + 25
    df = pd.DataFrame({"id": list(range(total))})
    run = _RunSpy(df=df)

    res = _serve(_FakeDB(), question, run)

    assert res is not None
    assert res.row_count == total
    assert len(res.rows) == serve.MAX_SERVE_ROWS
    assert res.truncated is True


# --------------------------------------------------------------------------- #
# render_answer_markdown
# --------------------------------------------------------------------------- #
def test_render_basic_table_and_sql_fence():
    res = serve.ServeResult(
        question="top stores",
        sql="SELECT name, revenue FROM stores",
        columns=["name", "revenue"],
        rows=[["Acme", 100], ["Beta", 90]],
        row_count=2,
        truncated=False,
    )
    md = serve.render_answer_markdown(res)
    assert "name" in md and "revenue" in md
    assert "Acme" in md
    # markdown table separator row
    assert "---" in md
    assert "```sql" in md
    assert "SELECT name, revenue FROM stores" in md


def test_render_truncated_includes_first_n_of_m():
    res = serve.ServeResult(
        question="all stores",
        sql="SELECT id FROM stores",
        columns=["id"],
        rows=[[i] for i in range(serve.MAX_SERVE_ROWS)],
        row_count=serve.MAX_SERVE_ROWS + 25,
        truncated=True,
    )
    md = serve.render_answer_markdown(res)
    assert str(serve.MAX_SERVE_ROWS) in md
    assert str(serve.MAX_SERVE_ROWS + 25) in md


def test_render_empty_rows_does_not_crash():
    res = serve.ServeResult(
        question="nothing",
        sql="SELECT id FROM stores WHERE 1=0",
        columns=["id"],
        rows=[],
        row_count=0,
        truncated=False,
    )
    md = serve.render_answer_markdown(res)
    assert isinstance(md, str)
    assert md  # non-empty: should mention there are no rows
    assert "```sql" in md


def test_render_escapes_pipe_in_cell():
    res = serve.ServeResult(
        question="weird",
        sql="SELECT label FROM t",
        columns=["label"],
        rows=[["a|b"]],
        row_count=1,
        truncated=False,
    )
    md = serve.render_answer_markdown(res)
    assert "a\\|b" in md
    assert "a|b" not in md.replace("a\\|b", "")  # raw pipe must be escaped
