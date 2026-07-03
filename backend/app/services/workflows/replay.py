"""Replay a saved AnalysisWorkflow headless.

Creates a fresh report, re-runs each captured step prompt (with ``{param}``
substituted) through the normal completion pipeline foreground, then best-effort
builds a dashboard artifact from the produced charts (reusing
``routes/report_slides._generate_artifact``). Returns the produced report +
artifact ids.

Fail-soft: ``run_workflow`` NEVER raises — returns ``{"ok": False, "error": ...}``
on failure.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
        from app.services.data_source_service import DataSourceService
        from app.services.report_service import ReportService
        from app.services.completion_service import CompletionService
        from app.schemas.report_schema import ReportCreate
        from app.schemas.completion_schema import CompletionCreate, PromptSchema

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
        report_id = str(report.id)

        # --- 2. Run each step prompt foreground. ------------------------------
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
