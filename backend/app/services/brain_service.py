"""
Proactive insight daemon (Phase 8 write)
=========================================

Karpathy 2nd-Brain proactive insights: periodically look at the org's recent
PROVEN questions (the reasoning-cache signal) and have the model distill ONE
actionable, GENERALIZABLE business insight/instruction that a future answer
should keep in mind. That insight is captured as a PENDING, approval-gated
memory — it must never go live on its own.

Design rules honored (see CLAUDE.md HARD RULES 4 & 5):
- Gated by ``flags.INSIGHT_DAEMON`` (env ``HYBRID_INSIGHT_DAEMON``), default OFF
  — a fresh deploy runs no insight scan until the flag is explicitly enabled.
- LEADER-gated: the periodic tick only proceeds on the process that holds the
  scheduler leader lock (``try_acquire_scheduler_leader``) AND wins the cross-pod
  ``claim_scheduled_run`` claim — so N workers/replicas don't all scan at once.
- APPROVAL-gated: everything learned is written through
  ``InstructionService.create_instruction``, which wraps the new instruction in a
  draft/``pending_approval`` InstructionBuild. The build/approval gate keeps the
  insight invisible to the planner until an admin promotes it — we DO NOT touch
  ``Instruction.status`` to make it live (status='published' = content-ready;
  visibility is governed by the BUILD gate, not the instruction status). This
  mirrors the self-distiller's write pattern exactly.
- Surgical dedup: an exact normalized-text match against this org's existing
  ai-sourced Instructions -> skip (never clobber/duplicate an AI memory).

This module is intentionally side-effect-light: every public coroutine swallows
its own errors and degrades to a no-op so a scheduled scan never breaks a pod.
``run_insight_scan_for_org`` and ``run_insight_daemon_tick`` NEVER raise.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, List, Optional

# Reuse the cache store's deterministic normalizer so dedup here matches the
# same notion of "same text" used elsewhere in the brain.
from app.ai.brain.query_cache_store import normalize_question

logger = logging.getLogger(__name__)

# Reject insights that came back empty or too short to be a real rule.
MIN_INSTRUCTION_LEN = 12

# How many recent signals to feed the model, and how many orgs a single tick
# will scan (keep small so a tick is cheap and bounded).
DEFAULT_SIGNAL_LIMIT = 20
MAX_ORGS_PER_TICK = 10

# Scheduler identifiers for the leader/claim coordination + registration.
INSIGHT_SCAN_JOB_ID = "hybrid_insight_scan"
INSIGHT_DAEMON_JOB_ID = "hybrid_insight_daemon"


def build_insight_prompt(signals: List[str]) -> str:
    """Compose the one-shot insight prompt. Pure, deterministic.

    ``signals`` is a list of recent proven questions (and/or simple aggregate
    descriptions). Asks the model to emit ONE actionable, GENERALIZABLE business
    insight/instruction — not tied to any row's specific data values. Output is
    the instruction text only — no preamble, no markdown.
    """
    if signals:
        signal_lines = "\n".join("- {0}".format(str(s).strip()) for s in signals if str(s).strip())
    else:
        signal_lines = "(no recent questions)"
    return (
        "Below are recent, validated questions that users of this analytics "
        "workspace have been asking. Your job is to surface ONE proactive, "
        "actionable business insight or instruction that would make future "
        "answers better.\n\n"
        "Recent questions / signals:\n"
        "{0}\n\n".format(signal_lines)
        + "Write a single, actionable, GENERALIZABLE insight/instruction. It must:\n"
        "- describe a reusable pattern or rule, NOT facts specific to any one "
        "question's data values (no specific numbers, names, dates, or row values);\n"
        "- be concrete enough to act on;\n"
        "- be one short paragraph at most.\n\n"
        "Output ONLY the instruction text. No preamble, no quotes, no markdown."
    )


async def gather_insight_signals(
    db: Any,
    *,
    organization_id: str,
    limit: int = DEFAULT_SIGNAL_LIMIT,
) -> List[str]:
    """Return recent active QueryCache questions for the org as signal.

    Defensive: returns an empty list on any error (missing table, bad db, etc.)
    so the daemon degrades to a no-op rather than raising.
    """
    if db is None or not organization_id:
        return []
    try:
        from sqlalchemy import select

        from app.models.query_cache import QueryCache

        stmt = (
            select(QueryCache)
            .where(QueryCache.organization_id == organization_id)
            .where(QueryCache.status == "active")
            .where(QueryCache.deleted_at.is_(None))
            .order_by(QueryCache.last_used_at.desc().nullslast())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        signals: List[str] = []
        for r in rows:
            q = (getattr(r, "question_norm", None) or "").strip()
            if q:
                signals.append(q)
        return signals
    except Exception as e:  # never break the daemon on a signal-query failure
        logger.warning("insight gather_insight_signals failed: %s", e)
        return []


async def run_insight_scan_for_org(
    db: Any,
    *,
    organization: Any,
    user: Any,
    model: Any,
    create_instruction_fn: Optional[Callable[..., Awaitable[Any]]] = None,
    llm_inference: Optional[Callable[[str], str]] = None,
) -> Optional[str]:
    """Scan one org's recent signals into a PENDING, ai-sourced insight.

    Returns the new instruction id, or None when nothing was written:
    flag off / no signal / insight too short / dedup hit / error.
    NEVER raises — every step is guarded and degrades to a no-op.
    """
    try:
        # 1. Flag gate. Default OFF — fresh deploy scans nothing.
        from app.settings.hybrid_flags import flags

        if not flags.INSIGHT_DAEMON:
            return None

        org_id = getattr(organization, "id", None)
        if not org_id:
            return None

        # 2. Gather signal. Need at least one proven question to reason over.
        signals = await gather_insight_signals(db, organization_id=org_id)
        if not signals:
            return None

        # 3. Compose the one-shot prompt.
        prompt = build_insight_prompt(signals)

        # 4. Infer via the model. Default: lazy-build a one-shot LLM call.
        infer = llm_inference
        if infer is None:
            def infer(p: str) -> str:  # noqa: E306 - tiny lazy default
                from app.ai.llm.llm import LLM
                from app.dependencies import async_session_maker

                return LLM(model, usage_session_maker=async_session_maker).inference(p)

        text = (infer(prompt) or "").strip()
        if len(text) < MIN_INSTRUCTION_LEN:
            return None

        # 5. Surgical dedup — don't clobber/duplicate an existing AI memory.
        #    Exact normalized-text match against this org's non-deleted
        #    ai-sourced instructions -> skip (already captured).
        norm = normalize_question(text)
        try:
            from sqlalchemy import select

            from app.models.instruction import Instruction

            existing = (
                await db.execute(
                    select(Instruction)
                    .where(Instruction.organization_id == org_id)
                    .where(Instruction.source_type == "ai")
                    .where(Instruction.deleted_at.is_(None))
                )
            ).scalars().all()
            for row in existing:
                if normalize_question(row.text or "") == norm:
                    return None  # already captured — skip
        except Exception:
            # Treat any dedup-query failure as "no duplicate" and proceed.
            pass

        # 6. WRITE (approval-gated). The build/approval flow keeps this invisible
        #    to the planner until an admin approves it.
        if create_instruction_fn is not None:
            result = await create_instruction_fn(
                db,
                text=text,
                organization=organization,
                user=user,
                source_type="ai",
                category="insight",
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
            category="insight",
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
    except Exception as e:  # never break a scheduled scan
        logger.warning("insight run_insight_scan_for_org failed: %s", e)
        return None


async def run_insight_daemon_tick(session_maker: Optional[Callable[[], Any]] = None) -> int:
    """Leader-gated periodic entry point. Returns the count of insights written.

    Steps (all guarded; returns 0 on any error):
      1. Flag gate (off -> 0, without acquiring the leader lock).
      2. Win the per-pod scheduler leader lock, else 0.
      3. Win the cross-pod scheduled-run claim, else 0.
      4. Open a session, resolve a small set of orgs + a default model,
         and run a scan per org. Return the number written.
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.INSIGHT_DAEMON:
            return 0
    except Exception:
        return 0

    # Leader + cross-pod claim. Both must succeed for THIS process to proceed.
    try:
        from app.core.scheduler import claim_scheduled_run, try_acquire_scheduler_leader

        if not try_acquire_scheduler_leader():
            return 0
        if not claim_scheduled_run(INSIGHT_SCAN_JOB_ID):
            return 0
    except Exception as e:
        logger.warning("insight tick leader/claim failed: %s", e)
        return 0

    written = 0
    try:
        # Resolve our session factory defensively (lazy import).
        maker = session_maker
        if maker is None:
            from app.dependencies import async_session_maker

            maker = async_session_maker

        async with maker() as db:
            organizations = await _resolve_orgs(db)
            if not organizations:
                return 0
            user = await _resolve_actor(db)
            model = await _resolve_model(db)
            for org in organizations[:MAX_ORGS_PER_TICK]:
                try:
                    new_id = await run_insight_scan_for_org(
                        db,
                        organization=org,
                        user=user,
                        model=model,
                    )
                    if new_id:
                        written += 1
                except Exception:
                    # One org's failure must not abort the rest of the tick.
                    continue
    except Exception as e:
        logger.warning("insight run_insight_daemon_tick failed: %s", e)
        return written

    return written


BRAIN_GRAPH_JOB_ID = "hybrid_brain_graph_mine"


async def run_brain_graph_daemon_tick(session_maker: Optional[Callable[[], Any]] = None) -> int:
    """Leader-gated periodic miner for BRAIN_GRAPH. Proposes PENDING correlation
    edges from each org's PUBLISHED entities (approval-gated; the reader only
    injects published edges). Without this tick nothing ever produces edges, so
    the injected graph section stays empty — this is the missing writer.

    Returns the count of orgs for which ≥1 edge was written. All guarded;
    returns 0 on any error or when HYBRID_BRAIN_GRAPH is off. Mirrors
    run_insight_daemon_tick's leader/claim/session discipline."""
    try:
        from app.settings.hybrid_flags import flags

        if not flags.BRAIN_GRAPH:
            return 0
    except Exception:
        return 0

    try:
        from app.core.scheduler import claim_scheduled_run, try_acquire_scheduler_leader

        if not try_acquire_scheduler_leader():
            return 0
        if not claim_scheduled_run(BRAIN_GRAPH_JOB_ID):
            return 0
    except Exception as e:
        logger.warning("brain-graph tick leader/claim failed: %s", e)
        return 0

    written = 0
    try:
        maker = session_maker
        if maker is None:
            from app.dependencies import async_session_maker

            maker = async_session_maker

        from app.ai.brain import brain_graph

        async with maker() as db:
            organizations = await _resolve_orgs(db)
            if not organizations:
                return 0
            model = await _resolve_model(db)
            for org in organizations[:MAX_ORGS_PER_TICK]:
                try:
                    res = await brain_graph.propose_edges_from_entities(
                        db, organization=org, model=model
                    )
                    if res and res.get("edges"):
                        written += 1
                        await db.commit()
                except Exception:
                    # One org's failure must not abort the rest of the tick.
                    continue
    except Exception as e:
        logger.warning("brain-graph run_brain_graph_daemon_tick failed: %s", e)
        return written

    return written


async def _resolve_orgs(db: Any) -> List[Any]:
    """Best-effort list of organizations to scan. [] on any error."""
    try:
        from sqlalchemy import select

        from app.models.organization import Organization

        stmt = select(Organization).limit(MAX_ORGS_PER_TICK)
        return list((await db.execute(stmt)).scalars().all())
    except Exception:
        return []


async def _resolve_actor(db: Any) -> Optional[Any]:
    """Best-effort system/admin user used as the create actor. None on error.

    A non-admin actor lands the write in pending_approval (the desired gate);
    None is also fine — the create path treats a missing actor as non-admin.
    """
    try:
        from sqlalchemy import select

        from app.models.user import User

        stmt = select(User).limit(1)
        return (await db.execute(stmt)).scalars().first()
    except Exception:
        return None


async def _resolve_model(db: Any) -> Optional[Any]:
    """Best-effort default/small LLM model for the one-shot inference. None on error."""
    try:
        from sqlalchemy import select

        from app.models.llm_model import LLMModel

        stmt = select(LLMModel).limit(1)
        return (await db.execute(stmt)).scalars().first()
    except Exception:
        return None


def register_insight_daemon(scheduler: Any) -> None:
    """Wire the insight tick onto the scheduler on an hourly interval.

    NOT called here — the parent agent wires this into scheduler startup. Only
    registers the job when ``flags.INSIGHT_DAEMON`` is on; dependency-light and
    guarded so a wiring mistake can never crash startup.
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.INSIGHT_DAEMON:
            return
        if scheduler is None:
            return
        scheduler.add_job(
            run_insight_daemon_tick,
            trigger="interval",
            hours=1,
            id=INSIGHT_DAEMON_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    except Exception as e:  # never let registration crash scheduler startup
        logger.warning("insight register_insight_daemon failed: %s", e)
