"""Studio examples API (hybrid Studios ST7/ST8 — golden few-shot examples).

Per-studio golden Q->answer (->SQL) examples the context assembler injects into a
Studio chat once they are ``active``. Examples are either *auto-born* by the
bootstrap pipeline / learning loop (``source='auto'``, mined from the query bank,
born ``pending`` behind the review gate) or *hand-written* by an editor
(``source='manual'``, created straight to ``active``). Only ``active`` examples
ever reach the model — ``pending`` rows are proposals awaiting a human approve.

Additive: this NEVER mutates the ``studios`` or ``data_sources`` tables — it only
reads/writes ``studio_examples`` rows. All behavior is gated by ``flags.STUDIOS``
and every route resolves the caller's effective Studio role first.

This router is mounted under /api by main.py (registered as
``studio_examples.router``). Mirrors the conventions in
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
from app.models.studio import Studio, StudioExample
from app.models.user import User
from app.schemas.studio import (
    StudioContentStatus,
    StudioExampleCreate,
    StudioExampleResponse,
)
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may create / edit / approve / reject / delete examples.
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


async def _load_example(
    db: AsyncSession, studio_id: str, example_id: str
) -> StudioExample:
    """Load a non-deleted example belonging to this studio or raise 404."""
    res = await db.execute(
        select(StudioExample).where(
            StudioExample.id == example_id,
            StudioExample.studio_id == studio_id,
            StudioExample.deleted_at.is_(None),
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise AppError.not_found(
            "studio.example_not_found", "Studio example not found"
        )
    return row


def _to_read(row: StudioExample) -> StudioExampleResponse:
    return StudioExampleResponse(
        id=str(row.id),
        studio_id=str(row.studio_id),
        question=row.question,
        answer=row.answer,
        sql=row.sql,
        source=row.source,
        status=row.status,
        uses=row.uses or 0,
        score=row.score,
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


# --------------------------------------------------------------------------- #
# LIST (viewer+)
# --------------------------------------------------------------------------- #
@router.get(
    "/studios/{studio_id}/examples",
    response_model=List[StudioExampleResponse],
)
async def list_studio_examples(
    studio_id: str,
    status: Optional[StudioContentStatus] = None,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List a Studio's examples (viewer+), newest first.

    Optional ``?status=pending|active`` filters to one review state.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user)

    stmt = select(StudioExample).where(
        StudioExample.studio_id == studio_id,
        StudioExample.deleted_at.is_(None),
    )
    if status is not None:
        stmt = stmt.where(StudioExample.status == status.value)
    stmt = stmt.order_by(StudioExample.created_at.desc())

    res = await db.execute(stmt)
    return [_to_read(r) for r in res.scalars().all()]


# --------------------------------------------------------------------------- #
# CREATE (editor+) — manual examples go straight to 'active'
# --------------------------------------------------------------------------- #
@router.post(
    "/studios/{studio_id}/examples",
    response_model=StudioExampleResponse,
)
async def create_studio_example(
    studio_id: str,
    body: StudioExampleCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Hand-create a Studio example (editor+).

    A manual example authored by an editor is trusted -> created ``active`` so it
    reaches the model immediately (the review gate exists for *machine* drafts).
    An explicit ``status=pending`` in the body is still honored.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    await _load_studio(db, studio_id)

    question = (body.question or "").strip()
    answer = (body.answer or "").strip()
    if not question:
        raise AppError.bad_request(ErrorCode.VALIDATION, "question is required")
    if not answer:
        raise AppError.bad_request(ErrorCode.VALIDATION, "answer is required")

    source = body.source.value
    # Manual examples default to 'active'; honor an explicit pending request.
    status = body.status.value
    if source == "manual" and "status" not in body.model_fields_set:
        status = StudioContentStatus.active.value

    row = StudioExample(
        studio_id=studio_id,
        question=question,
        answer=answer,
        sql=(body.sql or None),
        source=source,
        status=status,
        score=body.score,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


# --------------------------------------------------------------------------- #
# PATCH (editor+) — edit question/answer/sql
# --------------------------------------------------------------------------- #
@router.patch(
    "/studios/{studio_id}/examples/{example_id}",
    response_model=StudioExampleResponse,
)
async def update_studio_example(
    studio_id: str,
    example_id: str,
    body: StudioExampleCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Edit a Studio example's question/answer/sql (editor+)."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_example(db, studio_id, example_id)

    question = (body.question or "").strip()
    answer = (body.answer or "").strip()
    if not question:
        raise AppError.bad_request(ErrorCode.VALIDATION, "question is required")
    if not answer:
        raise AppError.bad_request(ErrorCode.VALIDATION, "answer is required")

    row.question = question
    row.answer = answer
    row.sql = body.sql or None
    if body.score is not None:
        row.score = body.score

    await db.commit()
    await db.refresh(row)
    return _to_read(row)


# --------------------------------------------------------------------------- #
# APPROVE (editor+) — pending -> active
# --------------------------------------------------------------------------- #
@router.post(
    "/studios/{studio_id}/examples/{example_id}/approve",
    response_model=StudioExampleResponse,
)
async def approve_studio_example(
    studio_id: str,
    example_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Approve a pending example (editor+) -> flips status to ``active``."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_example(db, studio_id, example_id)

    row.status = StudioContentStatus.active.value
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


# --------------------------------------------------------------------------- #
# REJECT (editor+) — soft-delete the draft
# --------------------------------------------------------------------------- #
@router.post("/studios/{studio_id}/examples/{example_id}/reject")
async def reject_studio_example(
    studio_id: str,
    example_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Reject an example (editor+) -> soft-deletes the draft row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_example(db, studio_id, example_id)

    row.deleted_at = datetime.utcnow()
    await db.commit()
    return {
        "ok": True,
        "studio_id": studio_id,
        "example_id": example_id,
        "rejected": True,
    }


# --------------------------------------------------------------------------- #
# DELETE (editor+) — soft-delete
# --------------------------------------------------------------------------- #
@router.delete("/studios/{studio_id}/examples/{example_id}")
async def delete_studio_example(
    studio_id: str,
    example_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Delete a Studio example (editor+). Soft-deletes the row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_example(db, studio_id, example_id)

    row.deleted_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "studio_id": studio_id, "example_id": example_id}


# --------------------------------------------------------------------------- #
# REGENERATE (editor+) — re-mine pending examples from the query bank
# --------------------------------------------------------------------------- #
@router.post(
    "/studios/{studio_id}/examples/regenerate",
    response_model=List[StudioExampleResponse],
)
async def regenerate_studio_examples(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Re-run the bootstrap example miner over the Studio's pinned sources.

    Returns the freshly-proposed ``pending`` examples for the review gate. The
    bootstrap service is imported lazily so this route stays import-safe even if
    the service module is not yet present at import time.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id)

    from app.services.studio_bootstrap import regenerate_examples

    rows = await regenerate_examples(db, studio)
    return [_to_read(r) for r in (rows or [])]
