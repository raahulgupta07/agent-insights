"""Studio data-source pinning API (hybrid Studios ST2).

Pin existing Data Agents (DataSource rows) as the *sources* of a Studio. A
Studio chat is grounded only on the DataSources pinned here (retrieval scoping
lives in the schema context builder + report-create auto-population).

Additive: this NEVER mutates the `data_sources` table — it only references it
via the `studio_data_sources` join (StudioDataSource: studio_id, agent_id where
agent_id -> data_sources.id). All behavior is gated by flags.STUDIOS and every
route resolves the caller's effective Studio role first.

This router is mounted under /api by main.py (registered as
`studio_sources.router`).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.data_source import DataSource
from app.models.organization import Organization
from app.models.studio import StudioDataSource
from app.models.user import User
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may mutate a Studio's pinned sources (add/remove).
_EDITOR_ROLES = {"owner", "editor"}


class StudioSourcePin(BaseModel):
    """Request body to pin a Data Agent as a Studio source."""
    agent_id: str


class StudioSourceRead(BaseModel):
    """A pinned Data Agent source on a Studio (echoes the DataSource summary)."""
    id: str                      # StudioDataSource row id
    studio_id: str
    agent_id: str                # data_sources.id
    name: Optional[str] = None   # resolved DataSource name (echo-only)
    type: Optional[str] = None   # resolved DataSource type (echo-only)

    class Config:
        from_attributes = True


def _require_flag() -> None:
    """Short-circuit when the Studios feature is OFF (upstream-identical)."""
    if not flags.STUDIOS:
        raise AppError.not_found("studio.not_found", "Studio not found")


async def _require_role(
    db: AsyncSession, studio_id: str, user: User, *, editor: bool = False
) -> str:
    """Resolve the caller's effective role or raise 404/403.

    A 404 (not 403) is returned when the user has no access at all so the
    existence of a Studio isn't leaked to non-members.
    """
    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        raise AppError.not_found("studio.not_found", "Studio not found")
    if editor and role not in _EDITOR_ROLES:
        raise AppError.forbidden(
            ErrorCode.ACCESS_DENIED, "Editor or owner role required"
        )
    return role


@router.get("/studios/{studio_id}/sources", response_model=List[StudioSourceRead])
async def list_studio_sources(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List the Data Agents pinned as sources for a Studio (viewer+)."""
    _require_flag()
    await _require_role(db, studio_id, current_user)

    res = await db.execute(
        select(StudioDataSource)
        .where(
            StudioDataSource.studio_id == studio_id,
            StudioDataSource.deleted_at.is_(None),
        )
        .order_by(StudioDataSource.created_at.asc())
    )
    pins = list(res.scalars().all())
    if not pins:
        return []

    # Resolve DataSource display fields (org-scoped) in a single query.
    agent_ids = [p.agent_id for p in pins]
    ds_res = await db.execute(
        select(DataSource).where(
            DataSource.id.in_(agent_ids),
            DataSource.organization_id == organization.id,
        )
    )
    ds_by_id = {str(d.id): d for d in ds_res.scalars().all()}

    out: List[StudioSourceRead] = []
    for p in pins:
        ds = ds_by_id.get(str(p.agent_id))
        out.append(
            StudioSourceRead(
                id=str(p.id),
                studio_id=str(p.studio_id),
                agent_id=str(p.agent_id),
                name=getattr(ds, "name", None) if ds is not None else None,
                type=getattr(ds, "type", None) if ds is not None else None,
            )
        )
    return out


@router.post("/studios/{studio_id}/sources", response_model=StudioSourceRead)
async def pin_studio_source(
    studio_id: str,
    body: StudioSourcePin,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Pin a Data Agent as a Studio source (editor+). Idempotent (deduped)."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    # The pinned source must be a DataSource the caller's org actually owns.
    ds_res = await db.execute(
        select(DataSource).where(
            DataSource.id == body.agent_id,
            DataSource.organization_id == organization.id,
        )
    )
    ds = ds_res.scalar_one_or_none()
    if ds is None:
        raise AppError.not_found(
            ErrorCode.DATA_SOURCE_NOT_FOUND, "Data source not found"
        )

    # Dedupe: a (studio, agent) pin is unique. Return the existing row.
    existing_res = await db.execute(
        select(StudioDataSource).where(
            StudioDataSource.studio_id == studio_id,
            StudioDataSource.agent_id == body.agent_id,
            StudioDataSource.deleted_at.is_(None),
        )
    )
    pin = existing_res.scalar_one_or_none()
    if pin is None:
        pin = StudioDataSource(studio_id=studio_id, agent_id=body.agent_id)
        db.add(pin)
        await db.commit()
        await db.refresh(pin)

    return StudioSourceRead(
        id=str(pin.id),
        studio_id=str(pin.studio_id),
        agent_id=str(pin.agent_id),
        name=getattr(ds, "name", None),
        type=getattr(ds, "type", None),
    )


@router.delete("/studios/{studio_id}/sources/{agent_id}")
async def unpin_studio_source(
    studio_id: str,
    agent_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Unpin a Data Agent from a Studio (editor+). Soft-deletes the join row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    res = await db.execute(
        select(StudioDataSource).where(
            StudioDataSource.studio_id == studio_id,
            StudioDataSource.agent_id == agent_id,
            StudioDataSource.deleted_at.is_(None),
        )
    )
    pin = res.scalar_one_or_none()
    if pin is None:
        raise AppError.not_found("studio.source_not_found", "Studio source not found")

    # Soft-delete (matches resolve_studio_access / list filtering on deleted_at).
    from datetime import datetime

    pin.deleted_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "studio_id": studio_id, "agent_id": agent_id}
