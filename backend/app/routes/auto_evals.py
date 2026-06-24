"""Studio auto-eval API (hybrid).

One route: LLM-propose a handful of golden eval ``TestCase`` rows for a Studio,
grounded on the REAL aggregates of its first pinned Data Agent, so future
retrains can't silently regress the studio's answers. Creation only -- running
the goldens is a separate, existing flow.

Additive: this router writes only ``test_cases``/``test_suites`` rows (reusing
the eval models) and reads pinned sources. Mirrors the conventions in
``app.routes.studio_artifacts`` (deps, auth, AppError/ErrorCode, flag + role
helpers, ``tags=["studios"]``, no ``/api`` prefix). This router is mounted under
/api by main.py (the parent registers it).

NOTE: no ``from __future__ import annotations`` -- a body pydantic/dict param
behind future-annotations + a permission decorator can make FastAPI mis-read the
body as a query param (a known landmine in this repo).
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.knowledge.auto_evals import generate_evals_for_studio
from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.organization import Organization
from app.models.user import User
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may generate goldens (mirrors studio_artifacts._EDITOR_ROLES).
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


@router.post("/studios/{studio_id}/auto-evals")
async def generate_studio_auto_evals(
    studio_id: str,
    body: dict = Body(default={}),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """LLM-generate golden eval TestCases from the Studio's real data (editor+).

    Self-gates to ``{"disabled": True, "created": 0}`` when ``AUTO_EVALS`` is OFF.
    Never raises a 500 -- the service is fail-soft and returns a JSON dict.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    max_cases: Optional[int] = None
    if isinstance(body, dict):
        raw = body.get("max_cases")
        if raw is not None:
            try:
                max_cases = int(raw)
            except (TypeError, ValueError):
                max_cases = None

    kwargs = {} if max_cases is None else {"max_cases": max_cases}
    return await generate_evals_for_studio(
        db,
        organization=organization,
        current_user=current_user,
        studio_id=studio_id,
        **kwargs,
    )
