"""
Self-distiller (Phase 5 write)
==============================

Karpathy 2nd-Brain self-distillation: when a user thumbs-down (👎) an answer,
take the question + the bad answer (+ any follow-up correction the user typed)
and have the model distill ONE actionable, generalizable instruction that would
have prevented the mistake. That instruction is captured as a PENDING,
approval-gated memory — it must never go live on its own.

Design rules honored (see CLAUDE.md HARD RULES 4 & 5):
- Gated by ``flags.DISTILLER`` (env ``HYBRID_DISTILLER``), default OFF — a fresh
  deploy never distills anything until the flag is explicitly enabled.
- Everything learned is approval-gated. We DO NOT insert a raw
  ``Instruction(status='published')`` row. We route the write through
  ``InstructionService.create_instruction``, which wraps the new instruction in
  a draft/``pending_approval`` InstructionBuild. For a non-admin actor that
  build sits in ``pending_approval`` until an admin promotes it to the main
  build — so the distilled memory is invisible to the planner until approved.
  (``status='published'`` on the instruction itself only means "content ready";
  visibility is governed by the BUILD gate, not the instruction status.)
- Surgical dedup (Obsidian patch_content spirit): we never clobber or duplicate
  an existing AI memory. An exact normalized-text match -> skip.

This module is intentionally side-effect-light: every public coroutine swallows
its own errors and degrades to a no-op (returns None) so a 👎 never breaks the
request path. ``distill_and_store`` NEVER raises.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Optional

# Reuse the cache store's deterministic normalizer so dedup here matches the
# same notion of "same question/text" used elsewhere in the brain.
from app.ai.brain.query_cache_store import normalize_question

logger = logging.getLogger(__name__)

# Whitespace collapser for the pure merge helper (mirrors query_cache_store._WS).
_WS = re.compile(r"\s+")

# Reject distillations that came back empty or too short to be a real rule.
MIN_INSTRUCTION_LEN = 12


def merge_memory_text(existing_text: str, new_text: str) -> Optional[str]:
    """Decide whether ``new_text`` adds genuinely new nuance to ``existing_text``.

    Pure, deterministic — no LLM, no DB. This is the "surgical PATCH/append"
    upgrade to dedup: instead of always dropping a normalized duplicate, we only
    drop it when it truly adds nothing; otherwise we append the new nuance onto
    the existing memory WITHOUT clobbering the original (Obsidian patch_content
    spirit).

    Returns:
      * ``None`` when ``new_text`` is already fully covered by ``existing_text``
        — identical normalized form, or a subset/substring of the existing
        normalized text, or whitespace-only difference. True skip.
      * otherwise the merged string: the existing text plus the new information
        appended as one additional clean sentence, whitespace collapsed, with no
        duplicate sentences.
    """
    # Be tolerant of None/non-str — degrade gracefully, never raise.
    try:
        existing_text = existing_text or ""
        new_text = new_text or ""

        # Collapse whitespace for a clean comparison + clean output base.
        existing_clean = _WS.sub(" ", str(existing_text).strip())
        new_clean = _WS.sub(" ", str(new_text).strip())

        if not new_clean:
            return None  # nothing to add
        if not existing_clean:
            return new_clean  # nothing to merge into -> the new text stands alone

        norm_existing = normalize_question(existing_clean)
        norm_new = normalize_question(new_clean)

        # Already covered: identical, or the new nuance is a substring already
        # present in the existing memory (word-boundary-ish substring check on the
        # normalized forms). Whitespace-only diffs collapse to the same norm too.
        if not norm_new:
            return None
        if norm_new == norm_existing:
            return None
        if norm_new in norm_existing:
            return None

        # Also skip when EVERY sentence of the new text is already present (as a
        # normalized sentence) in the existing memory — avoids re-appending nuance
        # we already merged on a prior pass.
        existing_sentences = {
            normalize_question(s) for s in _split_sentences(existing_clean)
        }
        existing_sentences.discard("")
        new_sentences = [s for s in _split_sentences(new_clean) if s.strip()]
        if not new_sentences:
            return None

        novel = []
        for s in new_sentences:
            ns = normalize_question(s)
            if not ns:
                continue
            if ns in existing_sentences:
                continue
            if ns in norm_existing:  # sentence already embedded in existing text
                continue
            novel.append(s.strip())

        if not novel:
            return None  # every sentence already covered -> true skip

        # Append the novel nuance as additional sentence(s), preserving the
        # original verbatim. Ensure clean sentence separation.
        base = existing_clean.rstrip()
        if base and base[-1] not in ".!?":
            base = base + "."
        appended = " ".join(novel)
        if appended and appended[-1] not in ".!?":
            appended = appended + "."
        return _WS.sub(" ", (base + " " + appended).strip())
    except Exception:
        # Side-effect-light: never raise. Degrade to "true skip".
        return None


# Sentence splitter for the merge helper. Deterministic, dependency-free: split
# on sentence-final punctuation followed by whitespace, keeping it simple.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list:
    """Split ``text`` into sentence-ish chunks. Pure, deterministic."""
    if not text:
        return []
    return [p for p in _SENT_SPLIT.split(text.strip()) if p.strip()]


def build_distill_prompt(question: str, bad_answer: str, correction: Optional[str]) -> str:
    """Compose the one-shot distillation prompt. Pure, deterministic.

    Asks the model to emit ONE actionable, generalizable instruction (not tied
    to this row's specific data values) that would have prevented the bad
    answer. Output is the instruction text only — no preamble, no markdown.
    """
    correction_block = (
        f"User correction / what they actually wanted:\n{correction}\n\n"
        if correction
        else ""
    )
    return (
        "A user gave a thumbs-down to the answer below. Your job is to learn from "
        "this mistake by writing ONE instruction that would have prevented it.\n\n"
        f"Question:\n{question}\n\n"
        f"Bad answer (the one the user rejected):\n{bad_answer}\n\n"
        f"{correction_block}"
        "Write a single, actionable, GENERALIZABLE instruction that would steer a "
        "future answer correctly. It must:\n"
        "- describe a reusable rule, NOT facts specific to this question's data "
        "values (no specific numbers, names, dates, or row values);\n"
        "- be concrete enough to act on;\n"
        "- be one short paragraph at most.\n\n"
        "Output ONLY the instruction text. No preamble, no quotes, no markdown."
    )


async def gather_feedback_context(db: Any, completion: Any) -> dict:
    """Return ``{'question', 'bad_answer', 'correction'}`` for a 👎'd completion.

    - ``question``  = ``completion.prompt['content']`` (the prompt that was asked).
    - ``bad_answer`` = ``completion.completion['content']`` (the rejected answer).
    - ``correction`` = the content of the NEXT user turn in the same report
      (``turn_index`` > this completion's, ``role == 'user'``), if any, else None —
      i.e. what the user typed after the bad answer, often the implicit fix.

    Defensive throughout: missing/malformed JSON or absent keys -> '' for the
    text fields; any error fetching the sibling turn -> correction None.
    """

    def _content(obj: Any) -> str:
        # prompt / completion are JSON columns: dict with a 'content' key, but be
        # tolerant of a raw string or anything malformed.
        try:
            if isinstance(obj, dict):
                return str(obj.get("content") or "")
            if isinstance(obj, str):
                return obj
        except Exception:
            pass
        return ""

    # dash splits a turn into a user row (prompt) + a system row (completion);
    # resolve both sides from the paired sibling so we never get half a turn.
    from app.ai.brain.qa_pair import resolve_qa_pair
    question, bad_answer = await resolve_qa_pair(db, completion)

    correction: Optional[str] = None
    try:
        from sqlalchemy import select

        from app.models.completion import Completion

        stmt = (
            select(Completion)
            .where(Completion.report_id == completion.report_id)
            .where(Completion.turn_index > completion.turn_index)
            .where(Completion.role == "user")
            .order_by(Completion.turn_index.asc())
            .limit(1)
        )
        sibling = (await db.execute(stmt)).scalars().first()
        if sibling is not None:
            text = _content(getattr(sibling, "prompt", None))
            correction = text or None
    except Exception:
        # Never let the sibling lookup break distillation.
        correction = None

    return {"question": question, "bad_answer": bad_answer, "correction": correction}


async def distill_and_store(
    db: Any,
    *,
    organization: Any,
    user: Any,
    completion: Any,
    model: Any,
    create_instruction_fn: Optional[Callable[..., Awaitable[Any]]] = None,
    llm_inference: Optional[Callable[[str], str]] = None,
) -> Optional[str]:
    """Distill a 👎'd completion into a PENDING, ai-sourced instruction.

    Returns the new instruction id, or None when nothing was written:
    flag off / no usable context / distillation too short / dedup hit / error.
    NEVER raises — every step is guarded and degrades to a no-op.
    """
    try:
        # 1. Flag gate. Default OFF — fresh deploy distills nothing.
        from app.settings.hybrid_flags import flags

        if not flags.DISTILLER:
            return None

        # 2. Build the feedback context. Need at least a question + bad answer.
        ctx = await gather_feedback_context(db, completion)
        if not ctx.get("question") or not ctx.get("bad_answer"):
            return None

        # 3. Compose the one-shot prompt.
        prompt = build_distill_prompt(ctx["question"], ctx["bad_answer"], ctx.get("correction"))

        # 4. Distill via the model. Default: lazy-build a one-shot LLM call.
        infer = llm_inference
        if infer is None:
            def infer(p: str) -> str:  # noqa: E306 - tiny lazy default
                from app.ai.llm.llm import LLM
                from app.dependencies import async_session_maker

                return LLM(model, usage_session_maker=async_session_maker).inference(p)

        text = (infer(prompt) or "").strip()
        if len(text) < MIN_INSTRUCTION_LEN:
            return None

        # 5. Surgical dedup -> PATCH/append (Obsidian patch_content spirit).
        #    Previously: an exact normalized-text match against an existing
        #    ai-sourced memory unconditionally RETURNED None (dropped the new
        #    nuance). Now we patch/append instead of skipping.
        #
        #    We iterate this org's non-deleted ai-sourced instructions and, on the
        #    FIRST near-duplicate (normalized forms equal OR one is a substring of
        #    the other — i.e. the new text extends, is extended by, or matches an
        #    existing memory), we attempt a surgical merge and BREAK out of the
        #    skip-loop either way:
        #      * merge_memory_text(...) == None -> the new text adds nothing new ->
        #        keep the old behavior (return None, already captured).
        #      * merge_memory_text(...) == merged string -> the new text carries
        #        genuinely new nuance. Set ``text = merged`` and fall through to the
        #        SAME write step (step 6).
        #
        #    Why a NEW pending build instead of mutating the existing row in place:
        #    every learned write must stay approval-gated and reviewable (HARD RULE
        #    5). Routing a fresh pending/draft InstructionBuild through the gate lets
        #    an admin see the patched memory and supersede the old one on approval —
        #    we NEVER silently overwrite a live/published memory in place.
        norm = normalize_question(text)
        try:
            from sqlalchemy import select

            from app.models.instruction import Instruction

            org_id = getattr(organization, "id", None)
            existing = (
                await db.execute(
                    select(Instruction)
                    .where(Instruction.organization_id == org_id)
                    .where(Instruction.source_type == "ai")
                    .where(Instruction.deleted_at.is_(None))
                )
            ).scalars().all()
            for row in existing:
                row_norm = normalize_question(row.text or "")
                # Near-duplicate trigger: exact match, or one normalized form is a
                # substring of the other (the new text extends / is extended by the
                # existing memory). merge_memory_text makes the keep/skip decision.
                is_near_dup = bool(norm) and bool(row_norm) and (
                    row_norm == norm or norm in row_norm or row_norm in norm
                )
                if is_near_dup:
                    merged = merge_memory_text(row.text or "", text)
                    if merged is None:
                        return None  # already fully captured — true skip
                    # New nuance found -> proceed to write the patched memory as a
                    # fresh pending, approval-gated build.
                    text = merged
                    break
        except Exception:
            # Treat any dedup-query failure as "no duplicate" and proceed.
            pass

        # 6. WRITE (gated). The build/approval flow keeps this invisible to the
        #    planner until an admin approves it.
        if create_instruction_fn is not None:
            result = await create_instruction_fn(
                db,
                text=text,
                organization=organization,
                user=user,
                source_type="ai",
                category="learned",
                load_mode="intelligent",
            )
            if result is None:
                return None
            # The injected fn may return an id (str) or an object with .id.
            return str(getattr(result, "id", result))

        # Real path: route through InstructionService.create_instruction, which
        # wraps the new instruction in a draft/pending_approval InstructionBuild.
        # We DELIBERATELY do not touch Instruction.status to 'published-and-live';
        # status='published' = content-ready, the BUILD gate controls visibility.
        from app.schemas.instruction_schema import InstructionCreate
        from app.services.instruction_service import InstructionService

        data = InstructionCreate(
            text=text,
            category="learned",
            source_type="ai",
            load_mode="intelligent",
            status="published",
        )
        created = await InstructionService().create_instruction(
            db,
            data,
            current_user=user,
            organization=organization,
        )
        return str(created.id)
    except Exception as e:  # never break the request path on a 👎
        logger.warning("distiller distill_and_store failed: %s", e)
        return None
