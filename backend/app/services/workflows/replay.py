"""Replay a saved AnalysisWorkflow headless.

Creates a fresh report, re-runs each captured step prompt (with ``{param}``
substituted) through the normal completion pipeline foreground, then best-effort
builds a dashboard artifact from the produced charts (reusing
``routes/report_slides._generate_artifact``). Returns the produced report +
artifact ids.

Two entry points share the same step logic:
  * :func:`run_workflow` — SYNCHRONOUS, foreground. Creates the report AND runs
    every step in the caller's request session before returning. Fine for tiny
    workflows; blocks the request for multi-step ones. NEVER raises — returns
    ``{"ok": False, "error": ...}`` on failure.
  * :func:`run_workflow_bg` — BACKGROUND worker. The route creates the report
    first (returns its id immediately), then this runs the steps in its OWN
    fresh detached session (org/user/report/workflow reloaded BY PK, same
    greenlet-safe discipline as ``auto_artifact`` / ``per_user_connector``).
    The report + its completions ARE the progress surface — the FE polls
    ``GET /api/reports/{id}/completions``. NEVER raises.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Strong refs to in-flight background replays. asyncio only holds a WEAK ref to a
# task, so a fire-and-forget replay can be GC'd mid-run; keep it alive here and
# drop it on completion (same idiom as services/auto_artifact.py).
_BG_TASKS: "set[asyncio.Task]" = set()


def _substitute(prompt: str, params: Dict[str, Any], param_names: List[str]) -> str:
    """Replace ``{name}`` with the provided value for each known param name.

    Only substitutes declared params (regex-per-name), so literal JSON braces in
    a prompt are left untouched. Missing/None values collapse to ''.
    """
    out = prompt or ""
    for name in param_names or []:
        val = params.get(name) if isinstance(params, dict) else None
        val = "" if val is None else str(val)
        out = re.sub(r"(?<!\{)\{%s\}(?!\})" % re.escape(name), val, out)
    return out


def _param_names_from_schema(schema: Any) -> List[str]:
    try:
        items = (schema or {}).get("params") if isinstance(schema, dict) else None
        return [str(p.get("name")) for p in (items or []) if isinstance(p, dict) and p.get("name")]
    except Exception:  # noqa: BLE001
        return []


async def run_workflow(
    db: Any,
    *,
    organization_id: str,
    user: Any,
    workflow: Any,
    params: Optional[Dict[str, Any]] = None,
) -> dict:
    """Re-run a saved workflow's steps in a new report. NEVER raises.

    Returns ``{ok, report_id, artifact_id, steps_run, answers}`` on success, or
    ``{ok: False, error}`` on failure.
    """
    params = params or {}
    try:
        if workflow is None:
            return {"ok": False, "error": "workflow not found"}

        from app.models.organization import Organization

        organization = await db.get(Organization, str(organization_id))
        if organization is None:
            return {"ok": False, "error": "organization not found"}

        steps_json = getattr(workflow, "steps_json", None) or {}
        steps = steps_json.get("steps") if isinstance(steps_json, dict) else None
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "error": "workflow has no steps"}

        param_names = _param_names_from_schema(getattr(workflow, "params_schema_json", None))

        # --- 1. Fresh report, attaching the caller's active data sources. -----
        report = await create_workflow_report(
            db, workflow=workflow, user=user, organization=organization
        )
        report_id = str(report.id)

        # --- 2. Run each step prompt foreground. ------------------------------
        steps_run, answers = await _run_steps_into_report(
            db,
            report_id=report_id,
            steps=steps,
            params=params,
            param_names=param_names,
            user=user,
            organization=organization,
        )

        # --- 3. Best-effort dashboard from the produced charts. ---------------
        artifact_id = await _build_dashboard(db, report_id, user, organization)

        # --- 4. Bump run_count. -----------------------------------------------
        try:
            workflow.run_count = int(getattr(workflow, "run_count", 0) or 0) + 1
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()

        return {
            "ok": True,
            "report_id": report_id,
            "artifact_id": artifact_id,
            "steps_run": steps_run,
            "answers": answers,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("run_workflow failed: %s", e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": str(e)}


async def create_workflow_report(
    db: Any, *, workflow: Any, user: Any, organization: Any
) -> Any:
    """Create the empty report for a workflow run, attaching the caller's active
    data sources. Committed before return so its id is stable. Shared by the sync
    path and the route (which then kicks off the background replay)."""
    from app.services.data_source_service import DataSourceService
    from app.services.report_service import ReportService
    from app.schemas.report_schema import ReportCreate

    try:
        active = await DataSourceService().get_active_data_sources(db, organization, user)
        ds_ids = [str(getattr(ds, "id", "")) for ds in active if getattr(ds, "id", None)]
    except Exception:  # noqa: BLE001
        ds_ids = []

    wf_name = getattr(workflow, "name", None) or "Workflow"
    report = await ReportService().create_report(
        db=db,
        report_data=ReportCreate(
            title=f"Workflow: {wf_name}"[:200],
            data_sources=ds_ids,
        ),
        current_user=user,
        organization=organization,
    )
    await db.commit()
    return report


async def _run_steps_into_report(
    db: Any,
    *,
    report_id: str,
    steps: List[Any],
    params: Dict[str, Any],
    param_names: List[str],
    user: Any,
    organization: Any,
) -> Tuple[int, List[str]]:
    """Run each captured step prompt foreground into ``report_id``. One bad step
    is logged and skipped, never aborts the rest. Returns ``(steps_run, answers)``."""
    from app.services.completion_service import CompletionService
    from app.schemas.completion_schema import CompletionCreate, PromptSchema

    steps_run = 0
    answers: List[str] = []
    for st in steps:
        if not isinstance(st, dict):
            continue
        prompt_text = _substitute(str(st.get("prompt") or ""), params, param_names)
        if not prompt_text.strip():
            continue
        try:
            await CompletionService().create_completion(
                db=db,
                report_id=report_id,
                completion_data=CompletionCreate(
                    prompt=PromptSchema(content=prompt_text)
                ),
                current_user=user,
                organization=organization,
                background=False,
            )
            steps_run += 1
            ans = await _latest_answer(db, report_id)
            if ans:
                answers.append(ans)
        except Exception as step_err:  # noqa: BLE001 — one bad step shouldn't abort all
            logger.warning("workflow step failed (report %s): %s", report_id, step_err)
            continue
    return steps_run, answers


async def run_workflow_bg(
    *,
    report_id: str,
    workflow_id: str,
    organization_id: str,
    user_id: str,
    params: Optional[Dict[str, Any]] = None,
) -> None:
    """Background replay: run a saved workflow's steps into an ALREADY-created
    report, then best-effort build a dashboard + bump ``run_count``.

    Runs in its OWN fresh detached session — org/user/report/workflow are reloaded
    BY PK here (the request session's ORM objects are expired/detached by the time
    this fires). Fully fail-soft: NEVER raises. The report + its completions ARE
    the progress surface; the FE polls ``GET /api/reports/{id}/completions``.
    """
    params = params or {}
    from app.dependencies import async_session_maker

    try:
        async with async_session_maker() as db:
            try:
                from app.models.organization import Organization
                from app.models.user import User
                from app.models.report import Report
                from app.models.analysis_workflow import AnalysisWorkflow

                organization = await db.get(Organization, str(organization_id))
                user = await db.get(User, str(user_id))
                report = await db.get(Report, str(report_id))
                workflow = await db.get(AnalysisWorkflow, str(workflow_id))
                if not all([organization, user, report, workflow]):
                    return
                if str(getattr(report, "organization_id", "")) != str(organization_id):
                    return
                if getattr(report, "deleted_at", None) is not None:
                    return

                steps_json = getattr(workflow, "steps_json", None) or {}
                steps = steps_json.get("steps") if isinstance(steps_json, dict) else None
                if not isinstance(steps, list) or not steps:
                    return
                param_names = _param_names_from_schema(
                    getattr(workflow, "params_schema_json", None)
                )

                await _run_steps_into_report(
                    db,
                    report_id=str(report_id),
                    steps=steps,
                    params=params,
                    param_names=param_names,
                    user=user,
                    organization=organization,
                )
                await _build_dashboard(db, str(report_id), user, organization)

                try:
                    workflow.run_count = int(getattr(workflow, "run_count", 0) or 0) + 1
                    await db.commit()
                except Exception:  # noqa: BLE001
                    await db.rollback()
            except Exception as e:  # noqa: BLE001 — never propagate out of the bg task
                logger.warning("run_workflow_bg failed (report %s): %s", report_id, e)
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001 — session-open failure
        logger.warning("run_workflow_bg session failed (report %s): %s", report_id, e)


def schedule_run_workflow_bg(
    *,
    report_id: str,
    workflow_id: str,
    organization_id: str,
    user_id: str,
    params: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire-and-forget :func:`run_workflow_bg` with a STRONG task ref so it can't
    be GC'd mid-run. Fail-soft — scheduling never raises into the request."""
    try:
        task = asyncio.create_task(
            run_workflow_bg(
                report_id=str(report_id),
                workflow_id=str(workflow_id),
                organization_id=str(organization_id),
                user_id=str(user_id),
                params=params or {},
            )
        )
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
    except Exception:  # noqa: BLE001 — scheduling must never break the response
        logger.warning("run_workflow_bg scheduling skipped", exc_info=True)


async def _latest_answer(db: Any, report_id: str) -> str:
    """Latest system completion's answer text for a report. Guarded → ''."""
    try:
        from sqlalchemy import select
        from app.models.completion import Completion

        c = (
            await db.execute(
                select(Completion)
                .where(Completion.report_id == str(report_id), Completion.role == "system")
                .order_by(Completion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if c is None:
            return ""
        cj = getattr(c, "completion", None)
        return str(cj.get("content") or "") if isinstance(cj, dict) else ""
    except Exception:  # noqa: BLE001
        return ""


async def _build_dashboard(db: Any, report_id: str, user: Any, organization: Any) -> Optional[str]:
    """Reuse report_slides._generate_artifact(mode='page'). Fail-soft → None."""
    try:
        from app.routes.report_slides import _generate_artifact

        result = await _generate_artifact(
            mode="page", report_id=str(report_id),
            current_user=user, organization=organization, db=db,
        )
        return (result or {}).get("artifact_id")
    except Exception:  # noqa: BLE001 — no charts / builder failure is non-fatal
        return None
