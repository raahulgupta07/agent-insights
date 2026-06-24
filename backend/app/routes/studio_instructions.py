"""Studio instructions API (hybrid Studios ST7/ST8 — context harness rules).

Per-studio instructions / rules that the context assembler injects into a Studio
chat once they are ``active``. Rules are either *auto-born* by the bootstrap
pipeline / learning loop (``source='auto'``, born ``pending`` behind the review
gate) or *hand-written* by an editor (``source='manual'``, created straight to
``active``). Only ``active`` rules ever reach the model — ``pending`` rows are
proposals awaiting a human approve.

Additive: this NEVER mutates the ``studios`` or ``data_sources`` tables — it only
reads/writes ``studio_instructions`` rows. All behavior is gated by
``flags.STUDIOS`` and every route resolves the caller's effective Studio role
first.

This router is mounted under /api by main.py (registered as
``studio_instructions.router``). Mirrors the conventions in
``app.routes.studio_artifacts`` (deps, auth, AppError/ErrorCode, flag + role
helpers, ``tags=["studios"]``, no ``/api`` prefix).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.organization import Organization
from app.models.studio import Studio, StudioInstruction
from app.models.user import User
from app.schemas.studio import (
    StudioContentStatus,
    StudioInstructionCreate,
    StudioInstructionResponse,
)
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may create / edit / approve / reject / delete instructions.
_EDITOR_ROLES = {"owner", "editor"}


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


async def _load_instruction(
    db: AsyncSession, studio_id: str, instruction_row_id: str
) -> StudioInstruction:
    """Load a non-deleted instruction belonging to this studio or raise 404."""
    res = await db.execute(
        select(StudioInstruction).where(
            StudioInstruction.id == instruction_row_id,
            StudioInstruction.studio_id == studio_id,
            StudioInstruction.deleted_at.is_(None),
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise AppError.not_found(
            "studio.instruction_not_found", "Studio instruction not found"
        )
    return row


def _to_read(row: StudioInstruction) -> StudioInstructionResponse:
    return StudioInstructionResponse(
        id=str(row.id),
        studio_id=str(row.studio_id),
        content=row.content,
        source=row.source,
        status=row.status,
        score=row.score,
        instruction_id=str(row.instruction_id) if row.instruction_id else None,
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


# --------------------------------------------------------------------------- #
# LIST (viewer+)
# --------------------------------------------------------------------------- #
@router.get(
    "/studios/{studio_id}/instructions",
    response_model=List[StudioInstructionResponse],
)
async def list_studio_instructions(
    studio_id: str,
    status: Optional[StudioContentStatus] = None,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List a Studio's instructions (viewer+), newest first.

    Optional ``?status=pending|active`` filters to one review state.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user)

    stmt = select(StudioInstruction).where(
        StudioInstruction.studio_id == studio_id,
        StudioInstruction.deleted_at.is_(None),
    )
    if status is not None:
        stmt = stmt.where(StudioInstruction.status == status.value)
    stmt = stmt.order_by(StudioInstruction.created_at.desc())

    res = await db.execute(stmt)
    return [_to_read(r) for r in res.scalars().all()]


# --------------------------------------------------------------------------- #
# CREATE (editor+) — manual rules go straight to 'active'
# --------------------------------------------------------------------------- #
@router.post(
    "/studios/{studio_id}/instructions",
    response_model=StudioInstructionResponse,
)
async def create_studio_instruction(
    studio_id: str,
    body: StudioInstructionCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Hand-create a Studio instruction (editor+).

    A manual rule authored by an editor is trusted -> created ``active`` so it
    reaches the model immediately (the review gate exists for *machine* drafts).
    An explicit ``status=pending`` in the body is still honored.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    await _load_studio(db, studio_id)

    content = (body.content or "").strip()
    if not content:
        raise AppError.bad_request(ErrorCode.VALIDATION, "content is required")

    source = body.source.value
    # Manual rules default to 'active'; honor an explicit pending request.
    status = body.status.value
    if source == "manual" and "status" not in body.model_fields_set:
        status = StudioContentStatus.active.value

    row = StudioInstruction(
        studio_id=studio_id,
        content=content,
        source=source,
        status=status,
        score=body.score,
        instruction_id=body.instruction_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


# --------------------------------------------------------------------------- #
# PATCH (editor+) — edit content
# --------------------------------------------------------------------------- #
@router.patch(
    "/studios/{studio_id}/instructions/{instruction_row_id}",
    response_model=StudioInstructionResponse,
)
async def update_studio_instruction(
    studio_id: str,
    instruction_row_id: str,
    body: StudioInstructionCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Edit a Studio instruction's content (editor+)."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_instruction(db, studio_id, instruction_row_id)

    content = (body.content or "").strip()
    if not content:
        raise AppError.bad_request(ErrorCode.VALIDATION, "content is required")

    row.content = content
    if body.score is not None:
        row.score = body.score

    await db.commit()
    await db.refresh(row)
    return _to_read(row)


# --------------------------------------------------------------------------- #
# APPROVE (editor+) — pending -> active
# --------------------------------------------------------------------------- #
@router.post(
    "/studios/{studio_id}/instructions/{instruction_row_id}/approve",
    response_model=StudioInstructionResponse,
)
async def approve_studio_instruction(
    studio_id: str,
    instruction_row_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Approve a pending instruction (editor+) -> flips status to ``active``."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_instruction(db, studio_id, instruction_row_id)

    row.status = StudioContentStatus.active.value
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


# --------------------------------------------------------------------------- #
# REJECT (editor+) — soft-delete the draft
# --------------------------------------------------------------------------- #
@router.post("/studios/{studio_id}/instructions/{instruction_row_id}/reject")
async def reject_studio_instruction(
    studio_id: str,
    instruction_row_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Reject an instruction (editor+) -> soft-deletes the draft row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_instruction(db, studio_id, instruction_row_id)

    row.deleted_at = datetime.utcnow()
    await db.commit()
    return {
        "ok": True,
        "studio_id": studio_id,
        "instruction_id": instruction_row_id,
        "rejected": True,
    }


# --------------------------------------------------------------------------- #
# DELETE (editor+) — soft-delete
# --------------------------------------------------------------------------- #
@router.delete("/studios/{studio_id}/instructions/{instruction_row_id}")
async def delete_studio_instruction(
    studio_id: str,
    instruction_row_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Delete a Studio instruction (editor+). Soft-deletes the row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_instruction(db, studio_id, instruction_row_id)

    row.deleted_at = datetime.utcnow()
    await db.commit()
    return {
        "ok": True,
        "studio_id": studio_id,
        "instruction_id": instruction_row_id,
    }


# --------------------------------------------------------------------------- #
# REGENERATE (editor+) — re-propose pending rules from schema
# --------------------------------------------------------------------------- #
@router.post(
    "/studios/{studio_id}/instructions/regenerate",
    response_model=List[StudioInstructionResponse],
)
async def regenerate_studio_instructions(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Re-run the bootstrap rule proposer over the Studio's pinned sources.

    Returns the freshly-proposed ``pending`` instructions for the review gate.
    The bootstrap service is imported lazily so this route stays import-safe
    even if the service module is not yet present at import time.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id)

    from app.services.studio_bootstrap import regenerate_instructions

    rows = await regenerate_instructions(db, studio)
    return [_to_read(r) for r in (rows or [])]
