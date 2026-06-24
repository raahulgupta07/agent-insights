"""Unit tests for the global LLM concurrency limiter.

Deterministic, no Postgres, no LLM, no app conftest fixtures. Importable under
``--noconftest`` and on Python 3.9 (no ``X | None`` syntax; we use Optional and
drive async tests via ``asyncio.run(...)`` inside sync test functions — the same
pattern as ``test_distiller.py`` — so we don't depend on the pytest-asyncio
plugin/mode being configured).

Contract under test (``app.ai.llm.concurrency``):
    * env unset            -> get_llm_semaphore() is None; llm_slot() no-op
    * LLM_MAX_CONCURRENCY=2 -> Semaphore(2); 3 holders serialize to max 2 live
    * invalid/<=0 values    -> None
    * _reset_for_tests()    -> clears the cached semaphore + loop
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from typing import Optional

# Load the concurrency module directly from its file path. Importing it via the
# normal ``app.ai.llm`` package would execute ``app/ai/llm/__init__.py``, which
# eagerly imports provider clients with optional native deps (e.g. google genai)
# that may not be installed in a bare unit-test environment. The concurrency
# module itself is stdlib-only, so loading it in isolation is safe and keeps the
# test runnable under ``--noconftest`` without those extras.
_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "app", "ai", "llm", "concurrency.py",
)
_spec = importlib.util.spec_from_file_location("_llm_concurrency_under_test", _MODULE_PATH)
concurrency = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(concurrency)


def _run(coro):
    return asyncio.run(coro)


def test_unset_returns_none_and_slot_is_noop(monkeypatch):
    monkeypatch.delenv("LLM_MAX_CONCURRENCY", raising=False)
    concurrency._reset_for_tests()

    assert concurrency.get_llm_semaphore() is None

    async def _go():
        ran = False
        async with concurrency.llm_slot():
            ran = True
        return ran

    assert _run(_go()) is True
    # No semaphore was ever constructed for the no-op path.
    assert concurrency._sem is None


def test_invalid_values_return_none(monkeypatch):
    for bad in ("abc", "0", "-1", "", "   ", "1.5"):
        monkeypatch.setenv("LLM_MAX_CONCURRENCY", bad)
        concurrency._reset_for_tests()
        assert concurrency.get_llm_semaphore() is None, "value %r should disable limiting" % bad


def test_positive_value_builds_semaphore(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "2")
    concurrency._reset_for_tests()

    async def _go():
        sem = concurrency.get_llm_semaphore()
        assert sem is not None
        # asyncio.Semaphore exposes its current value via _value.
        assert sem._value == 2
        return sem

    sem1 = _run(_go())
    assert sem1 is not None


def test_limit_serializes_concurrent_holders(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "2")
    concurrency._reset_for_tests()

    state = {"live": 0, "max_live": 0}

    async def _go():
        # Recreate the Event bound to this running loop.
        gate = asyncio.Event()
        started = []

        async def holder(idx):
            async with concurrency.llm_slot():
                state["live"] += 1
                state["max_live"] = max(state["max_live"], state["live"])
                started.append(idx)
                # Hold the slot until the gate opens so concurrency is observable.
                await gate.wait()
                state["live"] -= 1

        tasks = [asyncio.ensure_future(holder(i)) for i in range(3)]

        # Let the first wave acquire what it can. With cap=2, exactly 2 should
        # be live and the 3rd should be blocked on the semaphore.
        for _ in range(20):
            await asyncio.sleep(0)
            if state["live"] >= 2:
                break
        assert state["live"] == 2
        assert len(started) == 2  # 3rd holder is blocked, hasn't started body

        # Release everyone and let them drain.
        gate.set()
        await asyncio.gather(*tasks)
        return state["max_live"]

    max_live = _run(_go())
    # Never more than the cap ran concurrently.
    assert max_live == 2


def test_reset_clears_cache(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "3")
    concurrency._reset_for_tests()

    async def _build():
        return concurrency.get_llm_semaphore()

    sem = _run(_build())
    assert sem is not None
    # Cache populated.
    assert concurrency._sem is not None

    concurrency._reset_for_tests()
    assert concurrency._sem is None
    assert concurrency._sem_loop is None


def test_rebuilds_on_different_event_loop(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "2")
    concurrency._reset_for_tests()

    async def _build():
        return concurrency.get_llm_semaphore()

    # Each asyncio.run() uses a fresh event loop. The semaphore from the first
    # run is bound to a now-closed loop; the second run must rebuild it for its
    # own loop rather than reuse the stale (loop-mismatched) instance.
    sem1: Optional[asyncio.Semaphore] = _run(_build())
    sem2: Optional[asyncio.Semaphore] = _run(_build())
    assert sem1 is not None and sem2 is not None
    assert sem1 is not sem2
