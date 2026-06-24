"""HTTP surface for the deterministic WORKFLOW RUNNER (#5).

POST /api/workflows/{name}/run : run a named deterministic batch workflow
(fan a work-list through a stage worker with a per-item verifier gate) and
return its summary + per-item log. Flag-gated (HYBRID_WORKFLOWS), org-scoped,
approval-safe (the underlying jobs only PROPOSE pending knowledge).
"""

from __future__ import annotations

import logging

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


class RunWorkflowRequest(BaseModel):
    data_source_id: str
    max_tables: int = 25
    use_llm_judge: bool = False


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

    return await job(
        db=db,
        organization=organization,
        user=user,
        data_source=ds,
        max_tables=body.max_tables,
        use_llm_judge=body.use_llm_judge,
    )
