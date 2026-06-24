"""Unit tests for the serving funnel (cheap-tier fast-path before agent loop).

Deterministic, no Postgres, no LLM, no store internals. The funnel's only real
collaborator — ``try_serve_proven_query`` (Tier ②) — is monkeypatched with an
async fake, and ``render_answer_markdown`` is faked, so the funnel's ordering /
flag-gating / error-swallowing is tested in isolation. ``run_sql`` is a trivial
fake that is never actually invoked (Tier ② is mocked away).

Covers:
 - Tier ② serves on a ServeResult-like -> served, tier 'reasoning_cache',
   answer_md from the render fake, row_count propagated
 - Tier ② misses (None) with ① and ③ off -> agent_loop fall-through
 - Tier ② raises -> skipped gracefully, falls through, no exception propagates
 - ANSWER_CACHE flag on but ① stub returns None -> still falls through (proves
   the ① branch is reached and is safe)
"""
from __future__ import annotations

import asyncio

from app.ai.brain import serving_funnel as funnel


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeServeResult:
    """A stand-in for ServeResult — only ``row_count`` is read by the funnel."""

    def __init__(self, row_count):
        self.row_count = row_count


def _run_sql(sql):
    # Never actually called: Tier ② is mocked. Present only to satisfy the API.
    raise AssertionError("run_sql should not be invoked when try_serve is mocked")


def _run(coro):
    return asyncio.run(coro)


def _funnel():
    return _run(
        funnel.run_serving_funnel(
            object(),  # opaque db; never touched because try_serve is faked
            organization_id="org1",
            data_source_id="ds1",
            question="top stores",
            run_sql=_run_sql,
        )
    )


def _patch_try_serve(monkeypatch, *, result=None, raises=None):
    """Replace try_serve_proven_query with an async fake."""

    async def _fake(db, **kwargs):
        if raises is not None:
            raise raises
        return result

    monkeypatch.setattr(funnel, "try_serve_proven_query", _fake)


def _patch_render(monkeypatch, text="RENDERED_MD"):
    monkeypatch.setattr(funnel, "render_answer_markdown", lambda res: text)


def _flags_off(monkeypatch):
    """Turn off the optional ① and ③ tier flags."""
    for env in (
        "HYBRID_ANSWER_CACHE",
        "HYBRID_FEDERATION",
        "HYBRID_DUAL_SCHEMA",
    ):
        monkeypatch.delenv(env, raising=False)


# --------------------------------------------------------------------------- #
# Case 1: Tier ② serves
# --------------------------------------------------------------------------- #
def test_tier2_serves(monkeypatch):
    _flags_off(monkeypatch)
    # realism: Tier ② self-gates on these (moot under mock, but set anyway).
    monkeypatch.setenv("HYBRID_QUERY_CACHE", "1")
    monkeypatch.setenv("HYBRID_BRAIN_READ", "1")
    _patch_try_serve(monkeypatch, result=_FakeServeResult(row_count=7))
    _patch_render(monkeypatch, text="RENDERED_MD")

    out = _funnel()

    assert out.served is True
    assert out.tier == "reasoning_cache"
    assert out.tier == funnel.TIER_REASONING_CACHE
    assert out.answer_md == "RENDERED_MD"
    assert out.row_count == 7


# --------------------------------------------------------------------------- #
# Case 2: Tier ② misses, ① and ③ off -> agent loop
# --------------------------------------------------------------------------- #
def test_tier2_miss_falls_through_to_agent_loop(monkeypatch):
    _flags_off(monkeypatch)
    _patch_try_serve(monkeypatch, result=None)
    _patch_render(monkeypatch)

    out = _funnel()

    assert out.served is False
    assert out.tier == "agent_loop"
    assert out.tier == funnel.TIER_AGENT_LOOP
    assert out.answer_md is None
    assert out.row_count == 0


# --------------------------------------------------------------------------- #
# Case 3: Tier ② raises -> skipped gracefully, no propagation
# --------------------------------------------------------------------------- #
def test_tier2_raises_is_swallowed(monkeypatch):
    _flags_off(monkeypatch)
    _patch_try_serve(monkeypatch, raises=RuntimeError("serve blew up"))
    _patch_render(monkeypatch)

    # must NOT raise: degrades to the agent-loop fall-through.
    out = _funnel()

    assert out.served is False
    assert out.tier == funnel.TIER_AGENT_LOOP
    assert out.answer_md is None
    assert out.row_count == 0


# --------------------------------------------------------------------------- #
# Case 4: ANSWER_CACHE on but ① stub returns None -> still falls through
# --------------------------------------------------------------------------- #
def test_answer_cache_branch_reached_but_safe(monkeypatch):
    _flags_off(monkeypatch)
    monkeypatch.setenv("HYBRID_ANSWER_CACHE", "1")  # exercise the ① branch
    _patch_try_serve(monkeypatch, result=None)      # Tier ② also misses
    _patch_render(monkeypatch)

    out = _funnel()

    # ① stub returns None (not built) so we still fall through cleanly.
    assert out.served is False
    assert out.tier == funnel.TIER_AGENT_LOOP
    assert out.answer_md is None
    assert out.row_count == 0
