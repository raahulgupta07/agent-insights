"""Auto-artifact generation (HYBRID_AUTO_ARTIFACT, default OFF).

When a chat turn produces a DATASET (the agent ran ``create_data`` → ≥1
visualization/success step) but makes NO artifact, build a dashboard
(``mode='page'`` page artifact) in the BACKGROUND so the report's Outputs panel
isn't an empty "No artifacts yet" state.

This reuses the EXISTING one-click builder
(:func:`app.routes.report_slides._generate_artifact`, ``mode='page'``) — the
same pipeline the chat agent and the "Generate dashboard" button use — so the
produced artifact is identical. No new artifact builder.

Contract (all enforced in :func:`schedule_auto_artifact`):
  * Flag-gated — OFF ⇒ this module is byte-identical to a no-op.
  * Background — fire-and-forget ``asyncio.create_task`` with a STRONG ref
    (``_BG_TASKS``) so the task isn't garbage-collected mid-run (asyncio keeps
    only weak refs to tasks). Fresh detached DB session; org/report/user are
    reloaded BY PK inside that session (same discipline as the distiller / sync
    greenlet workers — never reuse the request session's expired ORM objects).
  * Fail-soft — every error is swallowed + logged; it NEVER raises into the
    chat response or the SSE stream.
  * Idempotent — skips if the report already has ANY artifact (the agent may
    have made one, or a prior auto-build did). This both avoids duplicates and
    respects the one-click ``max_total_artifact_calls`` breaker.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

# Strong references to in-flight background builds. asyncio.create_task only
# holds a WEAK ref to the task, so a fire-and-forget task can be collected mid
# run; keep it alive here and drop it on completion.
_BG_TASKS: "set[asyncio.Task]" = set()


async def _turn_produced_dataset(session, *, system_completion_id: str) -> bool:
    """True if THIS turn's system completion created ≥1 SUCCESS step — i.e.
    ``create_data`` actually ran and produced data (not just a prose answer).

    Walks the same chain the sense-making hook uses:
    completion → AgentExecution → ToolExecution.created_step_id → Step(success).
    """
    from app.models.agent_execution import AgentExecution
    from app.models.tool_execution import ToolExecution
    from app.models.step import Step

    ae_ids = (
        await session.execute(
            select(AgentExecution.id).where(
                AgentExecution.completion_id == system_completion_id
            )
        )
    ).scalars().all()
    if not ae_ids:
        return False
    step_ids = (
        await session.execute(
            select(ToolExecution.created_step_id).where(
                ToolExecution.agent_execution_id.in_(ae_ids),
                ToolExecution.created_step_id.isnot(None),
            )
        )
    ).scalars().all()
    if not step_ids:
        return False
    count = (
        await session.execute(
            select(func.count())
            .select_from(Step)
            .where(Step.id.in_(list(step_ids)), Step.status == "success")
        )
    ).scalar() or 0
    return count > 0


async def _build(
    *, report_id: str, organization_id: str, user_id: str, system_completion_id: str
) -> None:
    """Detached-session worker: gate, then call the one-click dashboard core."""
    from app.settings.database import create_async_session_factory
    from app.models.organization import Organization
    from app.models.report import Report
    from app.models.user import User
    from app.models.artifact import Artifact
    from app.models.visualization import Visualization

    async_session = create_async_session_factory()
    async with async_session() as session:
        try:
            # Reload everything BY PK in this fresh session (request-session ORM
            # objects are detached/expired here).
            report = await session.get(Report, report_id)
            organization = await session.get(Organization, organization_id)
            user = await session.get(User, user_id)
            if not all([report, organization, user]):
                return
            if getattr(report, "organization_id", None) != organization_id:
                return
            if getattr(report, "deleted_at", None) is not None:
                return

            # Idempotent: never auto-build if the report already has ANY artifact
            # (agent-made, prior auto-build, or one-click). Avoids duplicates and
            # the max_total_artifact_calls breaker.
            art_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Artifact)
                    .where(Artifact.report_id == report_id)
                )
            ).scalar() or 0
            if art_count:
                return

            # The builder assembles from the report's existing visualizations —
            # need ≥1 or it just 400s.
            viz_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Visualization)
                    .where(Visualization.report_id == report_id)
                )
            ).scalar() or 0
            if not viz_count:
                return

            # This specific turn produced a dataset (create_data ran).
            if not await _turn_produced_dataset(
                session, system_completion_id=str(system_completion_id)
            ):
                return

            # Reuse the EXACT one-click pipeline (mode='page'). It resolves the
            # org default LLM, runs CreateArtifactTool, and self-cleans a failed
            # artifact. Raises HTTPException on its own failure modes — all caught
            # below.
            from app.routes.report_slides import _generate_artifact

            await _generate_artifact(
                mode="page",
                report_id=str(report_id),
                current_user=user,
                organization=organization,
                db=session,
            )
            logger.info("auto-artifact: built dashboard for report %s", report_id)
        except Exception:  # noqa: BLE001 — never affect the chat response/stream
            logger.warning(
                "auto-artifact build skipped for report %s", report_id, exc_info=True
            )


def schedule_auto_artifact(
    *,
    report_id: str,
    organization_id: str,
    user_id: str,
    system_completion_id: str,
    report_mode: "str | None" = None,
) -> None:
    """Schedule a background dashboard build for a just-finished chat turn.

    Flag-gated, fail-soft, idempotent. NEVER raises into the caller — safe to
    call from either completion path right after the run (answer + sense_making)
    has fully succeeded.
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.AUTO_ARTIFACT:
            return
        # Only the normal chat surface — skip slides-focus / non-chat report modes.
        if (report_mode or "chat") != "chat":
            return
        task = asyncio.create_task(
            _build(
                report_id=str(report_id),
                organization_id=str(organization_id),
                user_id=str(user_id),
                system_completion_id=str(system_completion_id),
            )
        )
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
    except Exception:  # noqa: BLE001 — scheduling must never break the response
        logger.warning("auto-artifact scheduling skipped", exc_info=True)
