"""Studio self-improvement API (hybrid Studios ST8).

Manual "improve now" trigger for a Studio's self-learning loop. Runs the three
learning passes (``app.services.studio_learning.improve_studio``) on demand:

  * promote proven Q->SQL from the studio's traffic   -> PENDING examples (review gate)
  * distill recurring 👎 / failures into rules         -> PENDING rules    (review gate)
  * refresh most-asked questions                        -> LIVE suggested questions

Rules + examples land ``pending`` and only reach the model after a human approves
them via the existing studio review gate (``routes/studio_instructions.py`` /
``routes/studio_examples.py``). Only suggested-questions is written LIVE.

Additive: this NEVER mutates the ``studios`` or ``data_sources`` tables — it only
reads existing completion/feedback/query-bank rows scoped to the studio and
writes ``studio_examples`` / ``studio_instructions`` / ``studio_artifacts`` rows.
All behavior is gated by ``flags.STUDIOS`` and every route resolves the caller's
effective Studio role first.

This router is mounted under /api by main.py (registered as
``studio_learning.router`` by sibling agent B). Mirrors the conventions in
``app.routes.studio_examples`` (deps, auth, AppError/ErrorCode, flag + role
helpers, ``tags=["studios"]``, no ``/api`` prefix).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.organization import Organization
from app.models.studio import Studio
from app.models.user import User
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may trigger a learning pass (it proposes pending content + rewrites
# the live suggested questions).
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


# --------------------------------------------------------------------------- #
# IMPROVE NOW (editor+) — run the three learning passes on demand.
# --------------------------------------------------------------------------- #
@router.post("/studios/{studio_id}/improve")
async def improve_studio_now(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Run the studio self-improvement loop now (editor+).

    Returns ``{'examples': n, 'rules': n, 'suggested': n}`` — how many pending
    examples + pending rules were proposed and how many live suggested questions
    were published this pass. Examples + rules require human approval before they
    reach the model; suggested questions are live immediately.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id)

    from app.services.studio_learning import improve_studio

    counts = await improve_studio(db, studio)
    return {
        "ok": True,
        "studio_id": studio_id,
        "examples": int((counts or {}).get("examples", 0)),
        "rules": int((counts or {}).get("rules", 0)),
        "suggested": int((counts or {}).get("suggested", 0)),
    }
