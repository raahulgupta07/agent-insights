"""Auto-generated verified example SQL for a Studio's pinned sources.

ONE route: ``POST /studios/{studio_id}/auto-queries`` — asks the org's small
model for example analytical SELECT queries per pinned Data Source, verifies each
read-only against the live source, and saves the working ones to the Query
Library (status='approved', source='auto').

Mirrors ``app.routes.studio_artifacts`` conventions: ``tags=["studios"]``, no
``/api`` prefix (main.py mounts the router under /api), flag short-circuit via
``_require_flag()`` (Studios feature) and effective-role resolution
(``resolve_studio_access``, editor+). The work itself is in
``app.ai.knowledge.auto_queries`` which ALSO self-gates on ``flags.AUTO_QUERIES``
and never raises -> this route never 500s.

LANDMINE (intentional): NO ``from __future__ import annotations`` here. With a
permission/auth-decorated endpoint, stringized body annotations make FastAPI
mis-read the pydantic/dict body as a query param (422). The body is optional and
accepted as ``body: dict = Body(default={})``.
"""

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.ai.knowledge.auto_queries import generate_queries_for_studio
from app.models.organization import Organization
from app.models.user import User
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may trigger generation (editor+).
_EDITOR_ROLES = {"owner", "editor"}


def _require_flag() -> None:
    """Short-circuit when the Studios feature is OFF (upstream-identical 404)."""
    if not flags.STUDIOS:
        raise AppError.not_found("studio.not_found", "Studio not found")


async def _require_role(db: AsyncSession, studio_id: str, user: User) -> str:
    """Resolve the caller's effective Studio role or raise 404/403 (editor+)."""
    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        # 404 (not 403) so a Studio's existence isn't leaked to non-members.
        raise AppError.not_found("studio.not_found", "Studio not found")
    if role not in _EDITOR_ROLES:
        raise AppError.forbidden(ErrorCode.ACCESS_DENIED, "Editor or owner role required")
    return role


@router.post("/studios/{studio_id}/auto-queries")
async def generate_studio_auto_queries(
    studio_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Generate + verify example SQL for a Studio's pinned sources (editor+).

    Returns the generator's dict: ``{"ok": True, "saved": N, "by_source": {...},
    "skipped": M}``; ``{"disabled": True, "saved": 0}`` when the AUTO_QUERIES flag
    is OFF; ``{"ok": False, "error": ...}`` on a soft failure. Never 500s.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user)

    body = body if isinstance(body, dict) else {}
    try:
        max_per_source = int(body.get("max_per_source", 6))
    except Exception:
        max_per_source = 6

    return await generate_queries_for_studio(
        db,
        organization=organization,
        current_user=current_user,
        studio_id=studio_id,
        max_per_source=max_per_source,
    )
