"""Capture a report's finished analysis as a reusable AnalysisWorkflow.

The step plan = the report's ordered user prompts (the analysis questions the
user asked). Any ``{token}`` placeholder in a prompt becomes a workflow param.
We ALSO record the last data turn's produced columns (reference only), read via
the same eval-snapshot path the eval harness uses
(``services/eval_harness.make_result_set_rule_from_snapshot`` reads
``snapshot["create_data"]``), so a replay/caller can see what shape the analysis
produced.

Fail-soft: ``save_workflow_from_report`` NEVER raises — returns ``None`` on any
failure (and rolls back).
"""
from __future__ import annotations

import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# {name} placeholder — a single {identifier}. Excludes {{...}} (escaped) and any
# brace group containing non-identifier chars (so literal JSON in a prompt is
# never mistaken for a param).
_PARAM_RE = re.compile(r"(?<!\{)\{([a-zA-Z][a-zA-Z0-9_]*)\}(?!\})")

# Cap on captured steps — a workflow is a short repeatable plan, not a transcript.
_MAX_STEPS = 25


def extract_param_names(prompts: List[str]) -> List[str]:
    """Ordered, de-duplicated list of ``{token}`` param names across prompts."""
    seen: List[str] = []
    for p in prompts or []:
        if not isinstance(p, str):
            continue
        for name in _PARAM_RE.findall(p):
            if name not in seen:
                seen.append(name)
    return seen


def _params_schema(param_names: List[str]) -> dict:
    return {
        "params": [
            {"name": n, "label": n.replace("_", " ").strip().title() or n, "required": True}
            for n in param_names
        ]
    }


async def _report_step_prompts(db: Any, report_id: str) -> List[dict]:
    """Ordered user prompts for a report → ``[{n, prompt, source_completion_id}]``.

    A dash turn splits into a user row (``role='user'``, ``prompt['content']``)
    and a system row. We keep the user rows in turn order = the analysis plan.
    Guarded → [] on failure.
    """
    try:
        from sqlalchemy import select
        from app.models.completion import Completion

        rows = (
            await db.execute(
                select(Completion)
                .where(
                    Completion.report_id == str(report_id),
                    Completion.role == "user",
                    Completion.deleted_at.is_(None),
                )
                .order_by(Completion.turn_index.asc(), Completion.created_at.asc())
            )
        ).scalars().all()

        steps: List[dict] = []
        for c in rows:
            pj = getattr(c, "prompt", None)
            content = pj.get("content") if isinstance(pj, dict) else None
            if not isinstance(content, str) or not content.strip():
                continue
            steps.append(
                {
                    "n": len(steps) + 1,
                    "prompt": content.strip(),
                    "source_completion_id": str(getattr(c, "id", "") or "") or None,
                }
            )
            if len(steps) >= _MAX_STEPS:
                break
        return steps
    except Exception as e:  # noqa: BLE001
        logger.warning("workflows._report_step_prompts failed: %s", e)
        return []


async def _last_turn_result_columns(db: Any, report_id: str) -> List[str]:
    """Columns produced by the report's last data turn (reference only).

    Reuses the eval-snapshot extractor path: build the report's final snapshot
    and read ``snapshot['create_data']['columns']`` (exactly what
    ``eval_harness.make_result_set_rule_from_snapshot`` reads). Guarded → [].
    """
    try:
        from app.services.test_evaluation_service import TestEvaluationService

        snapshot = await TestEvaluationService().build_final_snapshot(db, str(report_id))
        cd = (snapshot or {}).get("create_data") or {}
        cols = cd.get("columns") if isinstance(cd, dict) else None
        return [str(c) for c in cols] if isinstance(cols, list) else []
    except Exception:  # noqa: BLE001
        return []


async def save_workflow_from_report(
    db: Any,
    *,
    organization_id: str,
    owner_user_id: Optional[str],
    report_id: str,
    name: str,
    scope: str = "private",
):
    """Save a report's analysis as a reusable, parameterized AnalysisWorkflow.

    Returns the created ``AnalysisWorkflow`` (committed) or ``None`` when there
    is nothing to capture / on any failure. NEVER raises.
    """
    try:
        org_id = str(organization_id or "")
        if not org_id or not report_id:
            return None

        steps = await _report_step_prompts(db, report_id)
        if not steps:
            logger.info("workflows: report %s has no capturable steps", report_id)
            return None

        param_names = extract_param_names([s["prompt"] for s in steps])
        result_columns = await _last_turn_result_columns(db, report_id)

        scope_val = "org" if str(scope) == "org" else "private"
        clean_name = (name or "").strip()[:300] or "Saved workflow"

        from app.models.analysis_workflow import AnalysisWorkflow

        wf = AnalysisWorkflow(
            organization_id=org_id,
            owner_user_id=str(owner_user_id) if owner_user_id else None,
            name=clean_name,
            description=None,
            steps_json={
                "steps": steps,
                "source_report_id": str(report_id),
                "result_columns": result_columns,
            },
            params_schema_json=_params_schema(param_names),
            scope=scope_val,
            run_count=0,
            status="active",
        )
        db.add(wf)
        await db.commit()
        await db.refresh(wf)
        return wf
    except Exception as e:  # noqa: BLE001
        logger.warning("save_workflow_from_report failed: %s", e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
