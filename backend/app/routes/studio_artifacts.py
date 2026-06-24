"""Studio artifacts API (hybrid Studios ST4).

NotebookLM-style artifacts attached to a Studio: an LLM-generated auto-summary,
FAQ or briefing (grounded on the schemas of the Studio's *pinned* Data Agents),
plus user-saved notes. Generation reuses the org's small default model via dash's
one-shot LLM wrapper and the knowledge-proposer schema renderer — no new LLM
infra (see ``app.services.studio_artifacts``).

Additive: this NEVER mutates the ``data_sources`` or ``studios`` tables — it only
reads pinned sources and writes ``studio_artifacts`` rows (StudioArtifact:
studio_id, kind, content). All behavior is gated by ``flags.STUDIOS`` and every
route resolves the caller's effective Studio role first.

This router is mounted under /api by main.py (registered as
``studio_artifacts.router``). Mirrors the conventions in
``app.routes.studio_sources`` (deps, auth, AppError/ErrorCode, flag + role
helpers, ``tags=["studios"]``, no ``/api`` prefix).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.organization import Organization
from app.models.studio import Studio, StudioArtifact
from app.models.user import User
from app.services.studio_access import resolve_studio_access
from app.services.studio_artifacts import GENERATED_KINDS, generate_artifact
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may generate / save / delete artifacts.
_EDITOR_ROLES = {"owner", "editor"}


class StudioArtifactGenerate(BaseModel):
    """Request body to LLM-generate an artifact ('summary'|'faq'|'briefing')."""
    kind: str


class StudioArtifactNote(BaseModel):
    """Request body to save a user note. ``kind`` defaults to 'note'."""
    kind: str = "note"
    content: str


class StudioArtifactRead(BaseModel):
    """An artifact attached to a Studio."""
    id: str
    studio_id: str
    kind: str
    content: Optional[str] = None
    created_at: Optional[datetime] = None

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


async def _load_studio(db: AsyncSession, studio_id: str) -> Studio:
    """Load a non-deleted Studio or raise 404."""
    res = await db.execute(
        select(Studio).where(
            Studio.id == studio_id,
            Studio.deleted_at.is_(None),
        )
    )
    studio = res.scalar_one_or_none()
    if studio is None:
        raise AppError.not_found("studio.not_found", "Studio not found")
    return studio


def _to_read(row: StudioArtifact) -> StudioArtifactRead:
    return StudioArtifactRead(
        id=str(row.id),
        studio_id=str(row.studio_id),
        kind=row.kind,
        content=row.content,
        created_at=getattr(row, "created_at", None),
    )


@router.get("/studios/{studio_id}/artifacts", response_model=List[StudioArtifactRead])
async def list_studio_artifacts(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List the artifacts attached to a Studio (viewer+), newest first."""
    _require_flag()
    await _require_role(db, studio_id, current_user)

    res = await db.execute(
        select(StudioArtifact)
        .where(
            StudioArtifact.studio_id == studio_id,
            StudioArtifact.deleted_at.is_(None),
        )
        .order_by(StudioArtifact.created_at.desc())
    )
    return [_to_read(r) for r in res.scalars().all()]


@router.post("/studios/{studio_id}/artifacts/generate", response_model=StudioArtifactRead)
async def generate_studio_artifact(
    studio_id: str,
    body: StudioArtifactGenerate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """LLM-generate an artifact over the Studio's pinned sources (editor+).

    ``kind`` must be one of summary/faq/briefing. Runs one cheap small-model
    inference, stores the result as a StudioArtifact and returns it.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id)

    kind = (body.kind or "").strip().lower()
    if kind not in GENERATED_KINDS:
        raise AppError.bad_request(
            ErrorCode.VALIDATION,
            f"kind must be one of {sorted(GENERATED_KINDS)}",
        )

    try:
        content = await generate_artifact(db, studio, kind, organization=organization)
    except ValueError as e:
        raise AppError.bad_request(ErrorCode.VALIDATION, str(e))

    row = StudioArtifact(studio_id=studio_id, kind=kind, content=content)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


@router.post("/studios/{studio_id}/artifacts", response_model=StudioArtifactRead)
async def save_studio_note(
    studio_id: str,
    body: StudioArtifactNote,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Save a user note as a Studio artifact (editor+). ``kind`` defaults to 'note'."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    await _load_studio(db, studio_id)

    content = (body.content or "").strip()
    if not content:
        raise AppError.bad_request(ErrorCode.VALIDATION, "content is required")

    kind = (body.kind or "note").strip().lower() or "note"

    row = StudioArtifact(studio_id=studio_id, kind=kind, content=content)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


@router.delete("/studios/{studio_id}/artifacts/{artifact_id}")
async def delete_studio_artifact(
    studio_id: str,
    artifact_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Delete an artifact from a Studio (editor+). Soft-deletes the row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    res = await db.execute(
        select(StudioArtifact).where(
            StudioArtifact.id == artifact_id,
            StudioArtifact.studio_id == studio_id,
            StudioArtifact.deleted_at.is_(None),
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise AppError.not_found("studio.artifact_not_found", "Studio artifact not found")

    row.deleted_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "studio_id": studio_id, "artifact_id": artifact_id}
