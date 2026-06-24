"""Studio self-improvement loop (hybrid Studios ST8).

A Studio learns from its OWN chat traffic. Capture is FREE — every chat inside a
studio is a ``Report`` with ``studio_id`` set (ST2), so its completions, feedback
and proven queries are already in the DB. This module reads those EXISTING rows
scoped to the studio's reports / pinned sources and turns them into:

  * ``promote_examples``   proven Q->SQL (query bank, hit_count>=N, no 👎)
                           -> StudioExample(source='auto', status='pending')   [review gate]
  * ``propose_rules``      recurring 👎 / repeated failures (reuse distiller)
                           -> StudioInstruction(source='auto', status='pending') [review gate]
  * ``refresh_suggested``  most-asked questions for this studio
                           -> StudioArtifact(kind='suggested_questions')        [LIVE, replace]
  * ``improve_studio``     runs all three and returns counts.

Design rules honored (CLAUDE.md HARD RULES 3/4/5):
  * NO new capture table — reuse Report/Completion/CompletionFeedback/QueryCache.
  * REUSE brain engines instead of editing them: the distiller's
    ``gather_feedback_context`` / ``build_distill_prompt`` for rule text, and
    ``query_cache_store.normalize_question`` for dedup/grouping. We only ever
    *read* the brain modules; we never mutate brain core.
  * Rules + examples are ALWAYS born ``pending`` (the existing studio review gate
    in ``routes/studio_instructions.py`` / ``routes/studio_examples.py`` promotes
    them). Only suggested-questions is written LIVE.
  * ``flags.STUDIOS`` gates everything; OFF -> every coroutine no-ops (returns 0 /
    empty), so a flag-OFF deploy is byte-identical.
  * Side-effect-light: every public coroutine swallows its own errors and
    degrades to a no-op so a learning pass can never break a request or a
    scheduler tick.

Thresholds are env-tunable (see the module-level ``_env_*`` helpers).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- #
# Env-tunable thresholds (all have safe defaults).
# ----------------------------------------------------------------------------- #
_DEFAULT_MIN_USES = 3          # proven-query hit floor before it becomes an example
_DEFAULT_MIN_DOWNVOTES = 2     # repeated-failure floor before we distill a rule
_DEFAULT_MAX_EXAMPLES = 10     # cap auto examples proposed per pass
_DEFAULT_MAX_RULES = 5         # cap auto rules proposed per pass
_DEFAULT_MAX_SUGGESTED = 6     # how many suggested questions to publish
_DEFAULT_MIN_QUESTION_ASKS = 2  # a question must recur this often to be "popular"

# The single shared artifact kind for studio starter questions. SHARED with the
# bootstrap agent (ST7) — both write this kind, so we always REPLACE, never add.
SUGGESTED_KIND = "suggested_questions"

# Minimum length for a distilled rule to be worth proposing.
_MIN_RULE_LEN = 12


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------------- #
# Scoping helpers — turn a studio into the set of rows it owns.
# ----------------------------------------------------------------------------- #
async def _studio_report_ids(db: AsyncSession, studio_id: str) -> List[str]:
    """Return the ids of all (non-deleted) reports that belong to this studio.

    This is the whole basis of ST8 scoping: chats inside a studio are Report rows
    with ``studio_id`` set, so everything downstream (completions, feedback) is
    reachable from these ids. Empty list when the studio has had no chats yet.
    """
    from app.models.report import Report

    try:
        res = await db.execute(
            select(Report.id).where(
                Report.studio_id == studio_id,
                Report.deleted_at.is_(None),
            )
        )
        return [str(r) for r in res.scalars().all()]
    except Exception as e:  # never raise into a learning pass
        logger.warning("studio_learning._studio_report_ids failed: %s", e)
        return []


async def _studio_data_source_ids(db: AsyncSession, studio_id: str) -> List[str]:
    """Return the ids of the Data Agents pinned to this studio (ST2 grounding).

    A studio's proven queries live in the org-wide ``query_cache`` keyed by
    ``data_source_id``; the studio's pinned sources are how we narrow that bank
    down to queries relevant to THIS studio.
    """
    from app.models.studio import StudioDataSource

    try:
        res = await db.execute(
            select(StudioDataSource.agent_id).where(
                StudioDataSource.studio_id == studio_id,
                StudioDataSource.deleted_at.is_(None),
            )
        )
        return [str(r) for r in res.scalars().all()]
    except Exception as e:
        logger.warning("studio_learning._studio_data_source_ids failed: %s", e)
        return []


# ----------------------------------------------------------------------------- #
# 1. promote_examples — proven Q->SQL from the query bank -> pending example.
# ----------------------------------------------------------------------------- #
async def promote_examples(db: AsyncSession, studio: Any) -> int:
    """Mine proven Q->SQL from this studio's traffic into PENDING examples.

    Reuses the reasoning-cache (``query_cache``): a row is "proven" when its
    ``hit_count >= STUDIO_LEARN_MIN_USES`` and it has never been thumbed-down
    (``thumbs_down == 0``). We scope the bank to the studio's org AND its pinned
    data sources (or org-wide NULL-scoped rows) so we don't pull in queries from
    unrelated studios.

    Each surviving proven query becomes a ``StudioExample(source='auto',
    status='pending')`` — invisible to the model until a human approves it.
    Deduped against the studio's existing examples by normalized question.

    Returns the number of new pending examples inserted (0 when flag-OFF, no
    proven queries, or all already proposed). Never raises.
    """
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS or studio is None:
        return 0

    studio_id = str(getattr(studio, "id", "") or "")
    org_id = getattr(studio, "organization_id", None)
    if not studio_id or not org_id:
        return 0

    min_uses = _env_int("STUDIO_LEARN_MIN_USES", _DEFAULT_MIN_USES)
    max_examples = _env_int("STUDIO_LEARN_MAX_EXAMPLES", _DEFAULT_MAX_EXAMPLES)

    try:
        from app.ai.brain.query_cache_store import normalize_question
        from app.models.query_cache import QueryCache
        from app.models.studio import StudioExample

        ds_ids = await _studio_data_source_ids(db, studio_id)

        stmt = (
            select(QueryCache)
            .where(QueryCache.organization_id == org_id)
            .where(QueryCache.hit_count >= min_uses)
            .where(QueryCache.thumbs_down == 0)
            .where(QueryCache.deleted_at.is_(None))
        )
        # Narrow to the studio's pinned sources (plus org-wide NULL rows). If the
        # studio has no pinned source yet, fall back to org-wide NULL-scoped rows
        # only so we never leak another studio's source-specific queries.
        if ds_ids:
            stmt = stmt.where(
                QueryCache.data_source_id.in_(ds_ids)
                | QueryCache.data_source_id.is_(None)
            )
        else:
            stmt = stmt.where(QueryCache.data_source_id.is_(None))
        stmt = stmt.order_by(QueryCache.hit_count.desc())

        proven = list((await db.execute(stmt)).scalars().all())
        if not proven:
            return 0

        # Existing examples (any status, incl. soft-deleted-aware) -> dedup set.
        existing_res = await db.execute(
            select(StudioExample.question).where(
                StudioExample.studio_id == studio_id,
                StudioExample.deleted_at.is_(None),
            )
        )
        seen = {normalize_question(q or "") for q in existing_res.scalars().all()}
        seen.discard("")

        inserted = 0
        for row in proven:
            if inserted >= max_examples:
                break
            question = (row.question_norm or "").strip()
            sql = (row.sql_text or "").strip()
            if not question or not sql:
                continue
            norm = normalize_question(question)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            db.add(
                StudioExample(
                    studio_id=studio_id,
                    question=question,
                    # The proven artifact is the SQL; the "answer" slot records
                    # provenance so a reviewer sees where it came from.
                    answer="(auto-mined from proven query — review & refine)",
                    sql=sql,
                    source="auto",
                    status="pending",
                    uses=int(row.hit_count or 0),
                    score=None,
                )
            )
            inserted += 1

        if inserted:
            await db.commit()
        return inserted
    except Exception as e:
        logger.warning("studio_learning.promote_examples failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


# ----------------------------------------------------------------------------- #
# 2. propose_rules — recurring 👎 / repeated failures -> pending rule.
# ----------------------------------------------------------------------------- #
async def propose_rules(db: AsyncSession, studio: Any) -> int:
    """Distill recurring failures in this studio's traffic into PENDING rules.

    Scopes to the studio's reports, finds completions that were thumbed-down
    (``CompletionFeedback.direction == -1``) OR errored, reuses the brain
    distiller's ``gather_feedback_context`` + ``build_distill_prompt`` to turn the
    worst recurring case(s) into ONE generalizable instruction each, and inserts
    them as ``StudioInstruction(source='auto', status='pending')`` — never live.

    Reuses the org's *small* default model via the same one-shot LLM wrapper the
    distiller / studio_artifacts use (no second LLM client). Deduped against the
    studio's existing instructions by normalized text.

    Returns the number of new pending rules inserted. Never raises.
    """
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS or studio is None:
        return 0

    studio_id = str(getattr(studio, "id", "") or "")
    org_id = getattr(studio, "organization_id", None)
    if not studio_id or not org_id:
        return 0

    min_downvotes = _env_int("STUDIO_LEARN_MIN_DOWNVOTES", _DEFAULT_MIN_DOWNVOTES)
    max_rules = _env_int("STUDIO_LEARN_MAX_RULES", _DEFAULT_MAX_RULES)

    try:
        from app.ai.brain.distiller import build_distill_prompt, gather_feedback_context
        from app.ai.brain.query_cache_store import normalize_question
        from app.models.completion import Completion
        from app.models.completion_feedback import CompletionFeedback
        from app.models.studio import StudioInstruction

        report_ids = await _studio_report_ids(db, studio_id)
        if not report_ids:
            return 0

        # Downvoted completions in this studio's reports, most-downvoted first.
        fb_stmt = (
            select(
                CompletionFeedback.completion_id,
                CompletionFeedback.direction,
            )
            .join(Completion, Completion.id == CompletionFeedback.completion_id)
            .where(Completion.report_id.in_(report_ids))
            .where(CompletionFeedback.direction == -1)
            .where(CompletionFeedback.deleted_at.is_(None))
        )
        fb_rows = (await db.execute(fb_stmt)).all()

        # Count downvotes per completion -> only "recurring" failures qualify.
        counts: Dict[str, int] = {}
        for completion_id, _direction in fb_rows:
            cid = str(completion_id)
            counts[cid] = counts.get(cid, 0) + 1

        candidates = sorted(
            (cid for cid, n in counts.items() if n >= min_downvotes),
            key=lambda cid: counts[cid],
            reverse=True,
        )
        if not candidates:
            return 0

        # Existing studio rules -> dedup set on normalized content.
        existing_res = await db.execute(
            select(StudioInstruction.content).where(
                StudioInstruction.studio_id == studio_id,
                StudioInstruction.deleted_at.is_(None),
            )
        )
        seen = {normalize_question(c or "") for c in existing_res.scalars().all()}
        seen.discard("")

        # Resolve the org's small/cheap model once (reuse, no new infra).
        infer = await _resolve_inference(db, studio, org_id)
        if infer is None:
            return 0

        inserted = 0
        for cid in candidates:
            if inserted >= max_rules:
                break
            completion = await db.get(Completion, cid)
            if completion is None:
                continue
            ctx = await gather_feedback_context(db, completion)
            if not ctx.get("question") or not ctx.get("bad_answer"):
                continue
            prompt = build_distill_prompt(
                ctx["question"], ctx["bad_answer"], ctx.get("correction")
            )
            try:
                text = (await _safe_infer(infer, prompt) or "").strip()
            except Exception:
                continue
            if len(text) < _MIN_RULE_LEN:
                continue
            norm = normalize_question(text)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            db.add(
                StudioInstruction(
                    studio_id=studio_id,
                    content=text,
                    source="auto",
                    status="pending",
                    score=float(counts.get(cid, 0)),
                )
            )
            inserted += 1

        if inserted:
            await db.commit()
        return inserted
    except Exception as e:
        logger.warning("studio_learning.propose_rules failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


# ----------------------------------------------------------------------------- #
# 3. refresh_suggested — most-asked questions -> LIVE suggested_questions.
# ----------------------------------------------------------------------------- #
async def refresh_suggested(db: AsyncSession, studio: Any) -> int:
    """Rebuild this studio's LIVE suggested-questions from its popular questions.

    Counts the user-role questions actually asked across the studio's reports,
    keeps the ones that recur at least ``STUDIO_LEARN_MIN_QUESTION_ASKS`` times,
    takes the top ``STUDIO_LEARN_MAX_SUGGESTED`` (by frequency, then recency
    order of appearance) and REPLACES the single shared
    ``StudioArtifact(kind='suggested_questions')`` row.

    This kind is SHARED with the bootstrap agent (ST7) — we ALWAYS replace the
    existing row (soft-delete prior rows of this kind, write one fresh row) so we
    never duplicate it. Suggested questions are mechanical + safe, so they are
    written LIVE (no review gate).

    Returns the number of suggested questions published (0 when flag-OFF or there
    aren't enough recurring questions yet). Never raises.
    """
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS or studio is None:
        return 0

    studio_id = str(getattr(studio, "id", "") or "")
    if not studio_id:
        return 0

    min_asks = _env_int("STUDIO_LEARN_MIN_QUESTION_ASKS", _DEFAULT_MIN_QUESTION_ASKS)
    max_suggested = _env_int("STUDIO_LEARN_MAX_SUGGESTED", _DEFAULT_MAX_SUGGESTED)

    try:
        import json
        from datetime import datetime

        from app.ai.brain.query_cache_store import normalize_question
        from app.models.completion import Completion
        from app.models.studio import StudioArtifact

        report_ids = await _studio_report_ids(db, studio_id)
        if not report_ids:
            return 0

        # User-role questions asked in this studio, oldest first (so first-seen
        # surface form is stable + we tie-break by earliest appearance).
        q_stmt = (
            select(Completion.prompt)
            .where(Completion.report_id.in_(report_ids))
            .where(Completion.role == "user")
            .where(Completion.deleted_at.is_(None))
            .order_by(Completion.turn_index.asc())
        )
        prompts = (await db.execute(q_stmt)).scalars().all()

        # Tally by normalized form, but keep the first verbatim surface form.
        counts: Dict[str, int] = {}
        surface: Dict[str, str] = {}
        order: List[str] = []
        for p in prompts:
            text = _prompt_content(p)
            if not text:
                continue
            norm = normalize_question(text)
            if not norm:
                continue
            if norm not in counts:
                counts[norm] = 0
                surface[norm] = text.strip()
                order.append(norm)
            counts[norm] += 1

        popular = [n for n in order if counts[n] >= min_asks]
        # Frequency desc, stable by first-appearance for ties.
        popular.sort(key=lambda n: (-counts[n], order.index(n)))
        chosen = [surface[n] for n in popular[:max_suggested]]
        if not chosen:
            return 0

        # REPLACE the shared kind: soft-delete any prior rows, write one fresh.
        now = datetime.utcnow()
        prior_res = await db.execute(
            select(StudioArtifact).where(
                StudioArtifact.studio_id == studio_id,
                StudioArtifact.kind == SUGGESTED_KIND,
                StudioArtifact.deleted_at.is_(None),
            )
        )
        for prior in prior_res.scalars().all():
            prior.deleted_at = now

        db.add(
            StudioArtifact(
                studio_id=studio_id,
                kind=SUGGESTED_KIND,
                content=json.dumps(chosen, ensure_ascii=False),
            )
        )
        await db.commit()
        return len(chosen)
    except Exception as e:
        logger.warning("studio_learning.refresh_suggested failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


# ----------------------------------------------------------------------------- #
# improve_studio — run all three.
# ----------------------------------------------------------------------------- #
async def improve_studio(db: AsyncSession, studio: Any) -> Dict[str, int]:
    """Run all three learning passes for ``studio`` and return the counts.

    Returns ``{'examples': n, 'rules': n, 'suggested': n}``. Each pass is
    independent + guarded, so a failure in one does not stop the others. No-op
    (all zeros) when ``flags.STUDIOS`` is off. Never raises.
    """
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS or studio is None:
        return {"examples": 0, "rules": 0, "suggested": 0}

    examples = await promote_examples(db, studio)
    rules = await propose_rules(db, studio)
    suggested = await refresh_suggested(db, studio)
    return {"examples": examples, "rules": rules, "suggested": suggested}


# ----------------------------------------------------------------------------- #
# Internal helpers (LLM + prompt-content extraction).
# ----------------------------------------------------------------------------- #
def _prompt_content(obj: Any) -> str:
    """Pull a 'content' string from a Completion.prompt JSON column."""
    try:
        if isinstance(obj, dict):
            return str(obj.get("content") or "")
        if isinstance(obj, str):
            return obj
    except Exception:
        pass
    return ""


async def _resolve_inference(db: AsyncSession, studio: Any, org_id: str):
    """Resolve a one-shot ``infer(prompt)->str`` callable on the org's small model.

    Returns ``None`` when no model is configured (caller no-ops). Mirrors the
    reuse shape in ``studio_artifacts`` / the distiller — dash's ``LLM.inference``
    is synchronous, so the returned callable is run off the event loop by
    ``_safe_infer``.
    """
    try:
        from app.models.organization import Organization
        from app.services.llm_service import LLMService

        organization = await db.get(Organization, org_id)
        if organization is None:
            return None
        model = await LLMService().get_default_model(
            db, organization, getattr(studio, "owner_user_id", None), is_small=True
        )
        if model is None:
            return None

        def _infer(prompt: str) -> str:
            from app.ai.llm.llm import LLM
            from app.dependencies import async_session_maker

            return LLM(model, usage_session_maker=async_session_maker).inference(prompt)

        return _infer
    except Exception as e:
        logger.warning("studio_learning._resolve_inference failed: %s", e)
        return None


async def _safe_infer(infer, prompt: str) -> str:
    """Run a synchronous ``infer(prompt)`` off the event loop. Never blocks it."""
    import asyncio

    return await asyncio.to_thread(infer, prompt)
