"""Unit tests for the Skills loader (Phase 6 read) + load_skill render path.

Deterministic, no Postgres, no LLM. A fake async DB returns canned result sets
(the SQLAlchemy WHERE / visibility clauses are not evaluated — we assert the
loader's logic: flag gating, row->dict shaping, and the planner-catalog render).

Mirrors backend/tests/unit/test_query_cache_store.py: same _FakeDB/_FakeResult
fakes, asyncio.run runner, and monkeypatch.setenv/delenv flag-toggling idiom.

Covers:
 - render_skill_catalog: empty -> '' (pure, always runnable)
 - render_skill_catalog: header + load_skill hint + one line per item
 - list_visible_skills / get_skill_body are no-ops when HYBRID_SKILLS is off
 - list_visible_skills (flag on) shapes rows into {id,name,description,scope}
 - get_skill_body (flag on) shapes a row into {id,name,description,skill_md,category}
   and returns None when no row is found
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.ai.skills import loader


# --------------------------------------------------------------------------- #
# Fakes (same shape as test_query_cache_store.py)
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
    """Returns a queued result per execute(); records executes consumed."""

    def __init__(self, results):
        self._results = list(results)
        self.executes = 0

    async def execute(self, stmt):
        self.executes += 1
        return self._results.pop(0)


def _skill_row(id="s1", name="Top Stores", description="rank outlets by revenue",
               scope="org", skill_md="# Top Stores\nrun it", category="analytics"):
    return SimpleNamespace(
        id=id,
        name=name,
        description=description,
        scope=scope,
        skill_md=skill_md,
        category=category,
    )


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# render_skill_catalog (pure — the load_skill catalog render path)
# --------------------------------------------------------------------------- #
def test_render_skill_catalog_empty():
    assert loader.render_skill_catalog([]) == ""


def test_render_skill_catalog_block():
    block = loader.render_skill_catalog([
        {"name": "Top Stores", "description": "rank outlets by revenue"},
        {"name": "Stockouts", "description": "find out-of-stock SKUs"},
    ])
    assert "## SKILLS" in block
    assert "load_skill" in block
    assert "Top Stores" in block
    assert "rank outlets by revenue" in block
    assert "Stockouts" in block
    assert "find out-of-stock SKUs" in block
    # one bullet per item
    assert block.count("\n- ") == 2


# --------------------------------------------------------------------------- #
# Flag OFF -> safe no-ops, DB untouched
# --------------------------------------------------------------------------- #
def test_list_visible_skills_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("HYBRID_SKILLS", raising=False)
    db = _FakeDB([])
    out = _run(loader.list_visible_skills(db, organization_id="org1", user_id="u1"))
    assert out == []
    assert db.executes == 0  # never touched the db


def test_get_skill_body_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("HYBRID_SKILLS", raising=False)
    db = _FakeDB([])
    out = _run(loader.get_skill_body(db, organization_id="org1", user_id="u1", name="Top Stores"))
    assert out is None
    assert db.executes == 0


# --------------------------------------------------------------------------- #
# Flag ON -> row shaping
# --------------------------------------------------------------------------- #
def test_list_visible_skills_shapes_rows(monkeypatch):
    monkeypatch.setenv("HYBRID_SKILLS", "1")
    rows = [
        _skill_row(id="s1", name="Top Stores", description="rank outlets by revenue", scope="org"),
        _skill_row(id="s2", name="Stockouts", description="find out-of-stock SKUs", scope="global"),
    ]
    db = _FakeDB([_FakeResult(rows)])
    out = _run(loader.list_visible_skills(db, organization_id="org1", user_id="u1"))
    assert len(out) == 2
    assert all(set(d.keys()) == {"id", "name", "description", "scope"} for d in out)
    assert out[0] == {"id": "s1", "name": "Top Stores",
                      "description": "rank outlets by revenue", "scope": "org"}
    assert out[1] == {"id": "s2", "name": "Stockouts",
                      "description": "find out-of-stock SKUs", "scope": "global"}


def test_get_skill_body_shapes_row(monkeypatch):
    monkeypatch.setenv("HYBRID_SKILLS", "1")
    row = _skill_row(id="s9", name="Top Stores", description="rank outlets by revenue",
                     skill_md="# Top Stores\nSELECT ...", category="analytics")
    db = _FakeDB([_FakeResult([row])])
    out = _run(loader.get_skill_body(db, organization_id="org1", user_id="u1", name="Top Stores"))
    assert out == {
        "id": "s9",
        "name": "Top Stores",
        "description": "rank outlets by revenue",
        "skill_md": "# Top Stores\nSELECT ...",
        "category": "analytics",
    }


def test_get_skill_body_none_when_no_row(monkeypatch):
    monkeypatch.setenv("HYBRID_SKILLS", "1")
    db = _FakeDB([_FakeResult([])])
    out = _run(loader.get_skill_body(db, organization_id="org1", user_id="u1", name="Nope"))
    assert out is None
