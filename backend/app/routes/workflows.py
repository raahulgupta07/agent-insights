"""HTTP surface for the deterministic WORKFLOW RUNNER (#5).

POST /api/workflows/{name}/run : run a named deterministic batch workflow
(fan a work-list through a stage worker with a per-item verifier gate) and
return its summary + per-item log. Flag-gated (HYBRID_WORKFLOWS), org-scoped,
approval-safe (the underlying jobs only PROPOSE pending knowledge).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.data_source import DataSource
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Static per-job presentation metadata for the LIST endpoint. Keyed by the
# registry name in `jobs.WORKFLOWS`. Unknown names fall back gracefully
# (see _workflow_meta) so the list never breaks when a job is added.
WORKFLOW_METADATA: dict[str, dict] = {
    "train_connector_tables": {
        "description": "Profile and train all connector tables",
        "max_concurrency": 1,
    },
}

# Lightweight in-process status store. Runs are synchronous/ephemeral (there is
# NO persisted run table), so this is the only record of the last run per
# workflow name. Survives only for the process lifetime; empty is fine.
_LAST_RUNS: dict[str, dict] = {}


def _humanize(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").title()


def _workflow_meta(name: str) -> dict:
    meta = WORKFLOW_METADATA.get(name, {})
    return {
        "name": name,
        "label": _humanize(name),
        "description": meta.get("description", ""),
        "max_concurrency": meta.get("max_concurrency"),
    }


class RunWorkflowRequest(BaseModel):
    data_source_id: str
    max_tables: int = 25
    use_llm_judge: bool = False


@router.get("")
async def list_workflows(
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    """List available deterministic workflows. Returns [] when the flag is off
    so the page can render an empty/disabled state (run_workflow 403s; a LIST
    is better empty)."""
    from app.settings.hybrid_flags import flags

    if not flags.WORKFLOWS:
        return []

    from app.ai.workflows import jobs

    return [_workflow_meta(name) for name in jobs.WORKFLOWS]


@router.get("/{name}/status")
async def get_workflow_status(
    name: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    """Last-run status for a workflow (in-process, ephemeral). Idle if never
    run this process lifetime."""
    return _LAST_RUNS.get(name) or {"status": "idle", "name": name}


@router.post("/{name}/run")
async def run_workflow(
    name: str,
    body: RunWorkflowRequest,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    from app.settings.hybrid_flags import flags

    if not flags.WORKFLOWS:
        raise HTTPException(
            status_code=403, detail="workflows are disabled (HYBRID_WORKFLOWS off)"
        )

    from app.ai.workflows import jobs

    job = jobs.WORKFLOWS.get(name)
    if job is None:
        raise HTTPException(status_code=404, detail=f"workflow '{name}' not found")

    ds = (
        await db.execute(
            select(DataSource).where(
                DataSource.id == body.data_source_id,
                DataSource.organization_id == organization.id,
            )
        )
    ).scalars().first()
    if ds is None:
        raise HTTPException(status_code=404, detail="data_source not found")

    try:
        summary = await job(
            db=db,
            organization=organization,
            user=user,
            data_source=ds,
            max_tables=body.max_tables,
            use_llm_judge=body.use_llm_judge,
        )
    except Exception as exc:  # noqa: BLE001 - record then re-raise unchanged
        _LAST_RUNS[name] = {
            "status": "error",
            "name": name,
            "error": str(exc),
            "finished_at": datetime.utcnow().isoformat(),
        }
        raise

    _LAST_RUNS[name] = {
        "status": "done",
        "name": name,
        "summary": summary,
        "finished_at": datetime.utcnow().isoformat(),
    }
    return summary
