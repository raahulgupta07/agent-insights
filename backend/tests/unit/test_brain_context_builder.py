"""Unit tests for the ContextHub BrainContextBuilder (proven-queries section).

Deterministic, no Postgres, no LLM. The builder's `recall_proven_queries` is
monkeypatched with an async fake so the build logic is tested in isolation from
the store's DB / normalization internals. The fake captures the kwargs it
receives so scoping (organization_id / data_source_id / question) is asserted.

Mirrors the `_run = asyncio.run` + monkeypatch idiom from
``tests/unit/test_query_cache_serve.py`` (no pytest-asyncio).

Covers:
 - query=None  -> empty section (.render()==""), recall NOT called
 - query="   " -> empty section, recall NOT called
 - recall returns 2 rows -> 2 matching items; render() has PROVEN QUERIES + cells
 - recall RAISES -> empty section, no exception propagates
 - data_source_ids scoping -> fake receives data_source_id == first id (or None)
 - direct section: empty renders "", populated renders the markdown block
"""
from __future__ import annotations

import asyncio
import types

import pytest

from app.ai.context.builders import brain_context_builder as bcb
from app.ai.context.sections.brain import ProvenQueriesSection, ProvenQueryItem


_run = asyncio.run


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _RecallSpy:
    """Async callable replacing recall_proven_queries.

    Records call count + the kwargs of the last call; returns `items` or raises.
    """

    def __init__(self, items=None, raises=None):
        self._items = list(items or [])
        self._raises = raises
        self.calls = 0
        self.last_kwargs = None

    async def __call__(self, db, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self._raises is not None:
            raise self._raises
        return list(self._items)


def _org(org_id="org1"):
    return types.SimpleNamespace(id=org_id)


def _patch_recall(monkeypatch, spy):
    monkeypatch.setattr(bcb, "recall_proven_queries", spy)
    return spy


def _build(db, organization, *, data_source_ids=None, query=None):
    builder = bcb.BrainContextBuilder(
        db, organization, data_source_ids=data_source_ids
    )
    return _run(builder.build(query=query))


# --------------------------------------------------------------------------- #
# Blank / None query -> recall never called
# --------------------------------------------------------------------------- #
def test_build_none_query_returns_empty_and_skips_recall(monkeypatch):
    spy = _patch_recall(monkeypatch, _RecallSpy(items=[{"question": "q", "sql": "SELECT 1"}]))
    section = _build(object(), _org(), query=None)
    assert isinstance(section, ProvenQueriesSection)
    assert section.items == []
    assert section.render() == ""
    assert spy.calls == 0


def test_build_whitespace_query_returns_empty_and_skips_recall(monkeypatch):
    spy = _patch_recall(monkeypatch, _RecallSpy(items=[{"question": "q", "sql": "SELECT 1"}]))
    section = _build(object(), _org(), query="   ")
    assert isinstance(section, ProvenQueriesSection)
    assert section.items == []
    assert section.render() == ""
    assert spy.calls == 0


# --------------------------------------------------------------------------- #
# Happy path -> items + rendered block
# --------------------------------------------------------------------------- #
def test_build_populates_items_and_renders_block(monkeypatch):
    rows = [
        {"question": "top stores", "sql": "SELECT 1"},
        {"question": "rev by month", "sql": "SELECT 2"},
    ]
    spy = _patch_recall(monkeypatch, _RecallSpy(items=rows))

    section = _build(object(), _org(), query="show me top stores")

    assert spy.calls == 1
    assert len(section.items) == 2
    assert all(isinstance(it, ProvenQueryItem) for it in section.items)
    assert section.items[0].question == "top stores"
    assert section.items[0].sql == "SELECT 1"
    assert section.items[1].question == "rev by month"
    assert section.items[1].sql == "SELECT 2"

    md = section.render()
    assert md  # non-empty
    assert "PROVEN QUERIES" in md
    assert "top stores" in md
    assert "SELECT 1" in md
    assert "```sql" in md


# --------------------------------------------------------------------------- #
# Recall raises -> empty section, no propagation
# --------------------------------------------------------------------------- #
def test_build_swallows_recall_exception(monkeypatch):
    spy = _patch_recall(monkeypatch, _RecallSpy(raises=RuntimeError("db down")))
    # must NOT raise; degrades to an empty section
    section = _build(object(), _org(), query="anything")
    assert isinstance(section, ProvenQueriesSection)
    assert section.items == []
    assert section.render() == ""
    assert spy.calls == 1  # it tried, then swallowed


# --------------------------------------------------------------------------- #
# Scoping: organization_id + data_source_id forwarded to recall
# --------------------------------------------------------------------------- #
def test_build_forwards_first_data_source_id(monkeypatch):
    spy = _patch_recall(monkeypatch, _RecallSpy(items=[]))
    _build(object(), _org("orgABC"), data_source_ids=["dsX", "dsY"], query="q")
    assert spy.calls == 1
    assert spy.last_kwargs.get("data_source_id") == "dsX"
    assert spy.last_kwargs.get("organization_id") == "orgABC"
    assert spy.last_kwargs.get("question") == "q"


def test_build_forwards_none_data_source_id_when_unset(monkeypatch):
    spy = _patch_recall(monkeypatch, _RecallSpy(items=[]))
    _build(object(), _org(), data_source_ids=None, query="q")
    assert spy.calls == 1
    assert spy.last_kwargs.get("data_source_id") is None


def test_build_forwards_none_data_source_id_when_empty_list(monkeypatch):
    spy = _patch_recall(monkeypatch, _RecallSpy(items=[]))
    _build(object(), _org(), data_source_ids=[], query="q")
    assert spy.calls == 1
    assert spy.last_kwargs.get("data_source_id") is None


# --------------------------------------------------------------------------- #
# Direct section behavior
# --------------------------------------------------------------------------- #
def test_section_empty_renders_blank():
    assert ProvenQueriesSection(items=[]).render() == ""


def test_section_populated_renders_markdown_block():
    section = ProvenQueriesSection(
        items=[ProvenQueryItem(question="top stores", sql="SELECT 1")]
    )
    md = section.render()
    assert md
    assert "PROVEN QUERIES" in md
    assert "top stores" in md
    assert "SELECT 1" in md
    assert "```sql" in md
