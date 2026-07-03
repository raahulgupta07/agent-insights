"""Workflows v2 — save & replay a finished analysis (HYBRID_WORKFLOWS_V2).

A user saves a report's analysis as a reusable, parameterized workflow and
replays it from the composer ("Use a workflow") so the same steps run
consistently for everyone. Org-scoped; a workflow is visible to its owner and
(when ``scope='org'``) to every member.

Router has NO prefix — main.py includes it with ``prefix="/api"`` (bare paths
here). Flag-gated on ``flags.WORKFLOWS_V2`` (default OFF): the list endpoint
returns ``{enabled: False, items: []}`` and every mutation 404s, so a fresh
deploy behaves exactly like upstream.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.organization import Organization
from app.models.user import User
from app.settings.hybrid_flags import flags

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workflows-v2"])


def _ensure_enabled() -> None:
    """404 (feature locked) unless HYBRID_WORKFLOWS_V2 is on — mirrors
    routes/report_slides so the route's existence isn't leaked when off."""
    if not flags.WORKFLOWS_V2:
        raise HTTPException(status_code=404, detail="Not found")


def _serialize(w) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "scope": w.scope,
        "owner_user_id": w.owner_user_id,
        "run_count": w.run_count,
        "status": w.status,
        "params": ((w.params_schema_json or {}).get("params") if isinstance(w.params_schema_json, dict) else []) or [],
        "step_count": len(((w.steps_json or {}).get("steps") if isinstance(w.steps_json, dict) else []) or []),
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


async def _load_visible(db, wf_id: str, org_id: str, user_id: str):
    """Load a workflow visible to the caller (owner or org-scoped). None if not."""
    from app.models.analysis_workflow import AnalysisWorkflow

    row = (
        await db.execute(
            select(AnalysisWorkflow).where(
                AnalysisWorkflow.id == str(wf_id),
                AnalysisWorkflow.organization_id == str(org_id),
                AnalysisWorkflow.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.scope == "org" or str(row.owner_user_id or "") == str(user_id):
        return row
    return None


@router.get("/workflows-v2")
async def list_workflows(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List workflows visible to the caller: their own + org-scoped ones."""
    if not flags.WORKFLOWS_V2:
        return {"enabled": False, "items": []}
    from app.models.analysis_workflow import AnalysisWorkflow

    rows = (
        await db.execute(
            select(AnalysisWorkflow)
            .where(
                AnalysisWorkflow.organization_id == str(organization.id),
                AnalysisWorkflow.deleted_at.is_(None),
                AnalysisWorkflow.status == "active",
                or_(
                    AnalysisWorkflow.scope == "org",
                    AnalysisWorkflow.owner_user_id == str(current_user.id),
                ),
            )
            .order_by(AnalysisWorkflow.updated_at.desc())
        )
    ).scalars().all()
    return {"enabled": True, "items": [_serialize(r) for r in rows]}


@router.post("/workflows-v2/from-report/{report_id}")
async def save_from_report(
    report_id: str,
    payload: dict = Body(default={}),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Save a report's analysis as a reusable workflow. Body: {name, scope}."""
    _ensure_enabled()

    # Org-scope the report (404 if not in this org).
    from app.models.report import Report

    report = (
        await db.execute(
            select(Report).where(
                Report.id == str(report_id),
                Report.organization_id == organization.id,
                Report.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    name = str((payload or {}).get("name") or report.title or "Saved workflow")
    scope = "org" if str((payload or {}).get("scope") or "") == "org" else "private"

    from app.services.workflows.capture import save_workflow_from_report

    wf = await save_workflow_from_report(
        db,
        organization_id=str(organization.id),
        owner_user_id=str(current_user.id),
        report_id=str(report_id),
        name=name,
        scope=scope,
    )
    if wf is None:
        raise HTTPException(
            status_code=400,
            detail="Nothing to save yet — this report has no analysis steps.",
        )
    return {"ok": True, "workflow": _serialize(wf)}


@router.post("/workflows-v2/{workflow_id}/run")
async def run_workflow_route(
    workflow_id: str,
    payload: dict = Body(default={}),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Replay a saved workflow with concrete params. Body: {params:{...}}."""
    _ensure_enabled()

    wf = await _load_visible(db, workflow_id, str(organization.id), str(current_user.id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    params = (payload or {}).get("params")
    if not isinstance(params, dict):
        params = {}

    from app.services.workflows.replay import run_workflow

    result = await run_workflow(
        db,
        organization_id=str(organization.id),
        user=current_user,
        workflow=wf,
        params=params,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Workflow run failed")
    return result


@router.delete("/workflows-v2/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Soft-delete a workflow (owner or org admin)."""
    _ensure_enabled()
    from app.models.analysis_workflow import AnalysisWorkflow

    row = (
        await db.execute(
            select(AnalysisWorkflow).where(
                AnalysisWorkflow.id == str(workflow_id),
                AnalysisWorkflow.organization_id == str(organization.id),
                AnalysisWorkflow.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    allowed = str(row.owner_user_id or "") == str(current_user.id)
    if not allowed:
        try:
            from app.core.permission_resolver import resolve_permissions, FULL_ADMIN

            r = await resolve_permissions(db, str(current_user.id), str(organization.id))
            allowed = FULL_ADMIN in r.org_permissions or r.has_org_permission("manage_connections")
        except Exception:  # noqa: BLE001
            allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed")

    row.deleted_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}
