"""Unit tests for the distiller's surgical PATCH/append dedup upgrade.

Deterministic, no Postgres, no LLM. We load the distiller module by FILE PATH
(importlib) so the package ``app/ai/brain/__init__.py`` / heavy lazy imports
never fire under ``--noconftest`` on Python 3.9 — same skip-guard spirit as
``test_llm_concurrency.py``. The distiller's module-level imports are light
(it only imports ``normalize_question`` from ``query_cache_store``, which is
stdlib-only), but we still guard by isolating the module load.

Covers:
 - merge_memory_text: identical -> None; fully-covered substring -> None;
   sentence-already-present -> None; whitespace-only diff -> None; empty new ->
   None; genuinely new nuance -> merged (contains original AND new, no dupes);
   empty existing -> new stands alone.
 - distill_and_store: an existing near-duplicate ai-instruction whose merge
   yields NEW nuance writes the MERGED text through create_instruction_fn.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from types import SimpleNamespace

# --------------------------------------------------------------------------- #
# Load the distiller module directly from its file path (skip-guard pattern).
# --------------------------------------------------------------------------- #
_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "app", "ai", "brain", "distiller.py",
)
_spec = importlib.util.spec_from_file_location("_distiller_under_test", _MODULE_PATH)
distiller = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(distiller)

merge_memory_text = distiller.merge_memory_text


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# merge_memory_text — pure helper
# --------------------------------------------------------------------------- #
def test_merge_identical_returns_none():
    base = "Always compare to the same period last year."
    assert merge_memory_text(base, base) is None


def test_merge_whitespace_only_diff_returns_none():
    base = "Always compare to the same period last year."
    noisy = "  Always   compare to the same   period last year.  "
    assert merge_memory_text(base, noisy) is None


def test_merge_case_and_trailing_punct_diff_returns_none():
    # normalize_question lowercases + strips trailing punctuation.
    base = "Always compare to the same period last year."
    variant = "ALWAYS compare to the same period last year!!"
    assert merge_memory_text(base, variant) is None


def test_merge_new_text_fully_covered_substring_returns_none():
    existing = "Always compare to the same period last year and exclude refunds."
    # The new text is a substring already fully present in existing.
    new = "Always compare to the same period last year"
    assert merge_memory_text(existing, new) is None


def test_merge_sentence_already_present_returns_none():
    existing = "Always compare year over year. Exclude refunds from revenue."
    new = "Exclude refunds from revenue."
    assert merge_memory_text(existing, new) is None


def test_merge_empty_new_returns_none():
    assert merge_memory_text("Always compare year over year.", "") is None
    assert merge_memory_text("Always compare year over year.", "   ") is None


def test_merge_empty_existing_returns_new_alone():
    new = "Always compare to the same period last year."
    out = merge_memory_text("", new)
    assert out is not None
    assert "Always compare to the same period last year." in out


def test_merge_new_nuance_appends_without_clobbering():
    existing = "Always compare to the same period last year."
    new = "Also exclude one-time refunds from the revenue total."
    out = merge_memory_text(existing, new)
    assert out is not None
    # Original preserved verbatim.
    assert "Always compare to the same period last year." in out
    # New nuance present.
    assert "exclude one-time refunds" in out.lower()
    # No duplicated sentence: each appears once.
    assert out.count("Always compare to the same period last year") == 1


def test_merge_appended_sentence_is_punctuated_and_collapsed():
    existing = "Compare year over year"          # no trailing period
    new = "Exclude refunds"                       # no trailing period
    out = merge_memory_text(existing, new)
    assert out is not None
    # Both clauses are terminated; whitespace collapsed (no double spaces).
    assert "  " not in out
    assert out.rstrip().endswith(".")
    assert "Compare year over year." in out
    assert "Exclude refunds." in out


def test_merge_only_novel_sentences_appended():
    existing = "Compare year over year. Exclude refunds."
    new = "Exclude refunds. Use net revenue not gross."
    out = merge_memory_text(existing, new)
    assert out is not None
    # The already-present "Exclude refunds" is not re-appended.
    assert out.lower().count("exclude refunds") == 1
    # The genuinely-new clause IS appended.
    assert "use net revenue not gross" in out.lower()


# --------------------------------------------------------------------------- #
# distill_and_store — near-duplicate present -> writes MERGED text via the seam
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
    """Returns a queued result per execute()."""

    def __init__(self, results=None):
        self._results = list(results or [])

    async def execute(self, stmt):
        if self._results:
            return self._results.pop(0)
        return _FakeResult([])

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _SpyCreate:
    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    async def __call__(self, db, **kwargs):
        self.calls.append(kwargs)
        return self.ret


def _completion():
    return SimpleNamespace(
        prompt={"content": "Why is revenue off?"},
        completion={"content": "that is wrong"},
        turn_index=0,
        report_id="r1",
        role="system",
    )


_ORG = SimpleNamespace(id="org1")
_USER = SimpleNamespace(id="u1")
_MODEL = object()


def test_distill_patches_existing_with_merged_text(monkeypatch):
    monkeypatch.setenv("HYBRID_DISTILLER", "1")

    existing_text = "Always compare to the same period last year."
    # The distilled instruction is a NEAR-duplicate of the existing memory: it
    # restates the existing rule (whose normalized form is a substring of the new
    # text) AND adds a genuinely-new nuance clause. The dedup loop's near-dup
    # trigger fires (existing norm is a substring of new norm), and
    # merge_memory_text appends the new clause -> the MERGED text is written.
    new_instruction = (
        "Always compare to the same period last year. "
        "Also exclude one-time refunds from the revenue total."
    )

    def llm(_prompt):
        return new_instruction

    create = _SpyCreate("merged-id")
    # The sibling lookup in gather_feedback_context fails its heavy import in a
    # bare unit env (no fastapi_mail) and consumes NO execute(), so the only
    # queued result is the dedup query -> the existing near-duplicate row.
    existing_row = SimpleNamespace(text=existing_text, source_type="ai")
    db = _FakeDB([_FakeResult([existing_row])])

    out = _run(
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

    assert out == "merged-id"
    assert len(create.calls) == 1
    written = create.calls[0]["text"]
    # The MERGED text was written: original preserved + new nuance appended.
    assert "Always compare to the same period last year." in written
    assert "exclude one-time refunds" in written.lower()
    # Still routed as an approval-gated ai/learned instruction.
    assert create.calls[0]["source_type"] == "ai"
    assert create.calls[0]["category"] == "learned"


def test_distill_skips_when_merge_adds_nothing(monkeypatch):
    monkeypatch.setenv("HYBRID_DISTILLER", "1")

    existing_text = "Always compare to the same period last year."

    def llm(_prompt):
        # Same nuance, differs only by case/punctuation -> merge returns None.
        return "ALWAYS compare to the same period last year!!"

    create = _SpyCreate("should-not-be-used")
    existing_row = SimpleNamespace(text=existing_text, source_type="ai")
    db = _FakeDB([_FakeResult([existing_row])])

    out = _run(
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

    assert out is None
    assert create.calls == []  # true skip, no duplicate write
