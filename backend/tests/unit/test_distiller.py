"""Unit tests for the self-distill DISTILLER module (Karpathy 2nd-Brain).

Deterministic, no Postgres, no LLM. We ALWAYS inject both ``llm_inference`` and
``create_instruction_fn`` so the module's heavy lazy imports
(``app.ai.llm.llm`` / ``app.dependencies`` / ``app.services.instruction_service``)
never fire — keeping these tests importable under ``--noconftest``.

The fake async ``db`` mirrors the ``_FakeDB`` / ``_FakeResult`` pattern in
``test_query_cache_store.py``; the SQLAlchemy WHERE clauses are not evaluated —
we drive the distiller's logic by handing it canned dedup result sets.

Covers the hard contract of ``app.ai.brain.distiller``:
 - distill_and_store is a no-op (returns None) unless HYBRID_DISTILLER=1
 - happy path writes via create_instruction_fn and returns the new id as str
   (create fn returning a bare id string AND returning an obj with ``.id``)
 - too-short / empty instruction text is rejected (no write)
 - missing question short-circuits before the LLM is called
 - surgical dedup: an existing org ai-instruction with the same normalized text
   skips the write
 - create_instruction_fn raising is swallowed (returns None, never propagates)
 - build_distill_prompt is a pure function over (question, bad_answer, correction)
 - gather_feedback_context pulls question/bad_answer from the completion
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.ai.brain import distiller


# --------------------------------------------------------------------------- #
# Fakes (mirror test_query_cache_store._FakeResult / _FakeDB)
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

    def __init__(self, results=None):
        self._results = list(results or [])
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        # If no canned results are queued, behave like "no rows".
        if self._results:
            return self._results.pop(0)
        return _FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _SpyLLM:
    """Sync callable -> str, records whether/how it was invoked."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        return self.reply


class _SpyCreate:
    """Async create_instruction_fn spy. Returns ``ret`` (bare id or has .id)."""

    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    async def __call__(self, db, **kwargs):
        self.calls.append(kwargs)
        return self.ret


class _RaisingCreate:
    def __init__(self):
        self.calls = []

    async def __call__(self, db, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("boom from create_instruction_fn")


def _completion(question="Why is revenue down?", bad="that is wrong", **over):
    base = dict(
        prompt={"content": question},
        completion={"content": bad},
        turn_index=0,
        report_id="r1",
        role="system",
    )
    base.update(over)
    return SimpleNamespace(**base)


_ORG = SimpleNamespace(id="org1")
_USER = SimpleNamespace(id="u1")
_MODEL = object()

_LONG = "Always compare to the same period last year."  # >= MIN_INSTRUCTION_LEN


def _run(coro):
    return asyncio.run(coro)


def _distill(db, llm, create, monkeypatch, flag=True):
    if flag:
        monkeypatch.setenv("HYBRID_DISTILLER", "1")
    else:
        monkeypatch.delenv("HYBRID_DISTILLER", raising=False)
    return _run(
        distiller.distill_and_store(
            db,
            organization=_ORG,
            user=_USER,
            completion=_completion(),
            model=_MODEL,
            create_instruction_fn=create,
            llm_inference=llm,
        )
    )


# --------------------------------------------------------------------------- #
# 1. flag OFF -> total no-op
# --------------------------------------------------------------------------- #
def test_distill_noop_when_flag_off(monkeypatch):
    llm = _SpyLLM(_LONG)
    create = _SpyCreate("new-id")
    out = _distill(_FakeDB(), llm, create, monkeypatch, flag=False)
    assert out is None
    assert llm.calls == []          # LLM not invoked
    assert create.calls == []       # nothing written


# --------------------------------------------------------------------------- #
# 2. happy path -> writes + returns created id as str (two return shapes)
# --------------------------------------------------------------------------- #
def test_distill_happy_path_bare_id(monkeypatch):
    llm = _SpyLLM(_LONG)
    create = _SpyCreate("instr-42")          # bare id string
    db = _FakeDB([_FakeResult([])])          # dedup: no existing row
    out = _distill(db, llm, create, monkeypatch)
    assert out == "instr-42"
    assert isinstance(out, str)
    assert len(llm.calls) == 1
    assert len(create.calls) == 1
    kw = create.calls[0]
    assert kw["text"] == _LONG
    assert kw["organization"] is _ORG
    assert kw["user"] is _USER
    assert kw["source_type"] == "ai"
    assert kw["category"] == "learned"
    assert kw["load_mode"] == "intelligent"


def test_distill_happy_path_object_with_id(monkeypatch):
    llm = _SpyLLM(_LONG)
    create = _SpyCreate(SimpleNamespace(id=99))   # object exposing .id
    db = _FakeDB([_FakeResult([])])
    out = _distill(db, llm, create, monkeypatch)
    assert out == "99"
    assert isinstance(out, str)
    assert len(create.calls) == 1


# --------------------------------------------------------------------------- #
# 3. instruction too short / empty -> rejected, no write
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("reply", ["", "  ", "too short", "x" * (distiller.MIN_INSTRUCTION_LEN - 1)])
def test_distill_rejects_short_instruction(monkeypatch, reply):
    llm = _SpyLLM(reply)
    create = _SpyCreate("nope")
    db = _FakeDB([_FakeResult([])])
    out = _distill(db, llm, create, monkeypatch)
    assert out is None
    assert create.calls == []       # never written


# --------------------------------------------------------------------------- #
# 4. missing question -> short-circuit before the LLM is called
# --------------------------------------------------------------------------- #
def test_distill_missing_question_short_circuits(monkeypatch):
    monkeypatch.setenv("HYBRID_DISTILLER", "1")
    llm = _SpyLLM(_LONG)
    create = _SpyCreate("new-id")
    out = _run(
        distiller.distill_and_store(
            _FakeDB(),
            organization=_ORG,
            user=_USER,
            completion=_completion(prompt={}),   # no 'content'
            model=_MODEL,
            create_instruction_fn=create,
            llm_inference=llm,
        )
    )
    assert out is None
    assert llm.calls == []          # LLM not even reached
    assert create.calls == []


# --------------------------------------------------------------------------- #
# 5. surgical dedup -> existing ai-instruction with same normalized text skips
# --------------------------------------------------------------------------- #
def test_distill_dedup_hit_skips_write(monkeypatch):
    llm = _SpyLLM(_LONG)
    create = _SpyCreate("should-not-be-used")
    # Existing row differs only by case + trailing punctuation, so normalized
    # forms match (normalize_question = lowercase / collapse / strip-trailing-punct).
    existing = SimpleNamespace(
        id="old-1",
        text="  ALWAYS compare to the same period last year!!  ",
        source_type="ai",
    )
    db = _FakeDB([_FakeResult([existing])])
    out = _distill(db, llm, create, monkeypatch)
    assert out is None
    assert create.calls == []       # dedup -> no duplicate write


# --------------------------------------------------------------------------- #
# 6. create_instruction_fn raises -> swallowed, returns None
# --------------------------------------------------------------------------- #
def test_distill_swallows_create_error(monkeypatch):
    llm = _SpyLLM(_LONG)
    create = _RaisingCreate()
    db = _FakeDB([_FakeResult([])])
    out = _distill(db, llm, create, monkeypatch)   # must NOT raise
    assert out is None
    assert len(create.calls) == 1   # we did attempt the write


# --------------------------------------------------------------------------- #
# 7. build_distill_prompt -> pure function over its inputs
# --------------------------------------------------------------------------- #
def test_build_distill_prompt_with_correction():
    q = "Why is revenue down this quarter?"
    bad = "Revenue went up by 12 percent."
    corr = "Revenue actually fell 8 percent versus last quarter."
    prompt = distiller.build_distill_prompt(q, bad, corr)
    assert isinstance(prompt, str) and prompt.strip()
    assert q in prompt
    assert bad in prompt
    assert corr in prompt


def test_build_distill_prompt_without_correction():
    q = "Which store leads on margin?"
    bad = "Store A leads."
    prompt = distiller.build_distill_prompt(q, bad, None)
    assert isinstance(prompt, str) and prompt.strip()
    assert q in prompt


# --------------------------------------------------------------------------- #
# 8. gather_feedback_context -> pulls question/bad_answer; no sibling -> None
# --------------------------------------------------------------------------- #
def test_gather_feedback_context_no_sibling():
    db = _FakeDB([_FakeResult([])])   # no next user turn in the report
    ctx = _run(distiller.gather_feedback_context(db, _completion()))
    assert ctx["question"] == "Why is revenue down?"
    assert ctx["bad_answer"] == "that is wrong"
    assert ctx["correction"] is None
