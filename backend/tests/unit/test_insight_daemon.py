"""Unit tests for the proactive insight daemon (Phase 8).

Deterministic, no Postgres, no LLM, no app conftest fixtures. Runnable under
``--noconftest`` and on Python 3.9 (no ``X | None`` syntax; async tests are
driven via ``asyncio.run(...)`` inside sync functions — the same pattern as
``test_llm_concurrency.py`` — so we don't depend on pytest-asyncio).

We import ``app.services.brain_service`` normally (its only import-time
dependency is ``app.ai.brain.query_cache_store``, which is stdlib-only). If that
import fails for an environment/py-version reason, the whole module skips — the
same skip-guard convention as ``test_quota_guard.py``.
"""

from __future__ import annotations

import asyncio

import pytest

try:
    from app.services import brain_service as bs

    _IMPORT_OK = True
except Exception as _exc:  # pragma: no cover - environment guard
    _IMPORT_OK = False
    _IMPORT_ERR = _exc

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="brain_service import failed (likely env/py-version dep): {0}".format(
        _IMPORT_ERR if not _IMPORT_OK else ""
    ),
)


def _run(coro):
    return asyncio.run(coro)


def _set_flag(monkeypatch, value):
    import app.settings.hybrid_flags as hf

    monkeypatch.setattr(type(hf.flags), "INSIGHT_DAEMON", property(lambda self: value))


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _Org:
    def __init__(self, id="org1"):
        self.id = id


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Async session that returns canned rows for every execute()."""

    def __init__(self, rows=None):
        self._rows = rows if rows is not None else []

    async def execute(self, *_a, **_k):
        return _Result(self._rows)


class _BoomSession:
    async def execute(self, *_a, **_k):
        raise RuntimeError("boom")


class _Row:
    def __init__(self, question_norm=None, text=None):
        self.question_norm = question_norm
        self.text = text


# ---------------------------------------------------------------------------
# Pure prompt builder
# ---------------------------------------------------------------------------

def test_prompt_builder_is_pure_deterministic():
    p1 = bs.build_insight_prompt(["top selling sku this month", "stock by outlet"])
    p2 = bs.build_insight_prompt(["top selling sku this month", "stock by outlet"])
    assert p1 == p2
    assert "top selling sku this month" in p1
    assert "Output ONLY the instruction text" in p1


def test_prompt_builder_handles_empty_signals():
    p = bs.build_insight_prompt([])
    assert isinstance(p, str)
    assert "(no recent questions)" in p


# ---------------------------------------------------------------------------
# Flag-off behavior
# ---------------------------------------------------------------------------

def test_scan_flag_off_returns_none(monkeypatch):
    _set_flag(monkeypatch, False)

    async def _bad_infer(_p):  # should never be called when flag off
        raise AssertionError("inference must not run when flag off")

    out = _run(
        bs.run_insight_scan_for_org(
            _FakeSession(),
            organization=_Org(),
            user=None,
            model=None,
            llm_inference=lambda p: "x" * 50,
        )
    )
    assert out is None


def test_tick_flag_off_returns_zero_without_leader(monkeypatch):
    _set_flag(monkeypatch, False)

    called = {"leader": False}

    def _leader():
        called["leader"] = True
        return True

    monkeypatch.setattr(bs, "try_acquire_scheduler_leader", _leader, raising=False)

    n = _run(bs.run_insight_daemon_tick())
    assert n == 0
    # Flag gate must short-circuit BEFORE the leader lock is touched.
    assert called["leader"] is False


# ---------------------------------------------------------------------------
# gather_insight_signals
# ---------------------------------------------------------------------------

def test_gather_signals_returns_empty_on_error():
    out = _run(bs.gather_insight_signals(_BoomSession(), organization_id="org1"))
    assert out == []


def test_gather_signals_empty_without_org():
    out = _run(bs.gather_insight_signals(_FakeSession(), organization_id=""))
    assert out == []


def test_gather_signals_extracts_questions():
    rows = [_Row(question_norm="q one"), _Row(question_norm=""), _Row(question_norm="q two")]
    out = _run(bs.gather_insight_signals(_FakeSession(rows), organization_id="org1"))
    assert out == ["q one", "q two"]


# ---------------------------------------------------------------------------
# Scan: dedup + success
# ---------------------------------------------------------------------------

def test_scan_dedup_hit_returns_none(monkeypatch):
    _set_flag(monkeypatch, True)

    insight = "Always segment sales by outlet before reporting totals."

    # Session returns the same question signal AND an existing ai instruction
    # whose normalized text matches the produced insight -> dedup skip.
    sig_rows = [_Row(question_norm="sales by outlet")]
    existing_rows = [_Row(text=insight)]

    class _Sess:
        def __init__(self):
            self._calls = 0

        async def execute(self, *_a, **_k):
            self._calls += 1
            # 1st execute = gather_insight_signals; 2nd = dedup lookup.
            return _Result(sig_rows if self._calls == 1 else existing_rows)

    async def _create(*_a, **_k):  # should never be reached on dedup hit
        raise AssertionError("create must not run on dedup hit")

    out = _run(
        bs.run_insight_scan_for_org(
            _Sess(),
            organization=_Org(),
            user=None,
            model=None,
            create_instruction_fn=_create,
            llm_inference=lambda p: insight,
        )
    )
    assert out is None


def test_scan_success_returns_id(monkeypatch):
    _set_flag(monkeypatch, True)

    captured = {}

    async def _create(db, **kwargs):
        captured.update(kwargs)
        return "new-instruction-id"

    out = _run(
        bs.run_insight_scan_for_org(
            _FakeSession([_Row(question_norm="top sku this month")]),
            organization=_Org(),
            user="u1",
            model=None,
            create_instruction_fn=_create,
            llm_inference=lambda p: "Prefer rolling 30-day windows when users ask about 'this month'.",
        )
    )
    assert out == "new-instruction-id"
    # Approval-gated provenance: written as an ai-sourced 'insight' memory.
    assert captured.get("source_type") == "ai"
    assert captured.get("category") == "insight"
    assert captured.get("load_mode") == "intelligent"


def test_scan_too_short_insight_returns_none(monkeypatch):
    _set_flag(monkeypatch, True)

    async def _create(*_a, **_k):
        raise AssertionError("create must not run for too-short insight")

    out = _run(
        bs.run_insight_scan_for_org(
            _FakeSession([_Row(question_norm="x")]),
            organization=_Org(),
            user=None,
            model=None,
            create_instruction_fn=_create,
            llm_inference=lambda p: "tiny",
        )
    )
    assert out is None


def test_scan_no_signal_returns_none(monkeypatch):
    _set_flag(monkeypatch, True)

    async def _create(*_a, **_k):
        raise AssertionError("create must not run with no signal")

    out = _run(
        bs.run_insight_scan_for_org(
            _FakeSession([]),  # gather -> no signals
            organization=_Org(),
            user=None,
            model=None,
            create_instruction_fn=_create,
            llm_inference=lambda p: "x" * 50,
        )
    )
    assert out is None


# ---------------------------------------------------------------------------
# Tick leader gating
# ---------------------------------------------------------------------------

def _install_fake_scheduler(monkeypatch, *, leader, claim):
    """Inject a stand-in ``app.core.scheduler`` so the tick's lazy import resolves.

    The real module imports apscheduler (often absent in a bare unit env), so we
    register a tiny fake with just the two coordination functions the tick uses.
    """
    import sys
    import types

    fake = types.ModuleType("app.core.scheduler")
    fake.try_acquire_scheduler_leader = leader
    fake.claim_scheduled_run = claim
    monkeypatch.setitem(sys.modules, "app.core.scheduler", fake)
    return fake


def test_tick_no_leader_returns_zero(monkeypatch):
    _set_flag(monkeypatch, True)
    _install_fake_scheduler(
        monkeypatch,
        leader=lambda: False,
        claim=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("claim must not run")),
    )
    n = _run(bs.run_insight_daemon_tick())
    assert n == 0


def test_tick_claim_lost_returns_zero(monkeypatch):
    _set_flag(monkeypatch, True)
    _install_fake_scheduler(
        monkeypatch,
        leader=lambda: True,
        claim=lambda *_a, **_k: False,
    )
    n = _run(bs.run_insight_daemon_tick())
    assert n == 0
