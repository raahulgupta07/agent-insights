"""Studio skill pinning API (hybrid Studios ST5).

Pin existing Skills (self-service Skills subsystem) to a Studio. The pinned set
is what scopes a Studio chat's offered skills — the NotebookLM differentiator:
a Studio only exposes the skills its owner/editors have curated for it, instead
of the user's whole visible catalog (see ``skill_context_builder.py``).

Additive: this NEVER mutates the ``skills`` table — it only references it via the
``studio_skills`` join (StudioSkill: studio_id, skill_id where skill_id ->
skills.id). All behavior is gated by flags.STUDIOS and every route resolves the
caller's effective Studio role first (viewer reads; editor+ mutates).

This router is mounted under /api by main.py (registered as
``studio_skills.router``).
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
from app.models.studio import StudioSkill
from app.models.user import User
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may mutate a Studio's pinned skills (pin/unpin).
_EDITOR_ROLES = {"owner", "editor"}


class StudioSkillPin(BaseModel):
    """Request body to pin a Skill to a Studio."""
    skill_id: str


class StudioSkillRead(BaseModel):
    """A pinned Skill on a Studio (echoes the Skill summary)."""
    id: str                          # StudioSkill row id
    studio_id: str
    skill_id: str                    # skills.id
    name: Optional[str] = None       # resolved Skill name (echo-only)
    description: Optional[str] = None  # resolved Skill description (echo-only)
    scope: Optional[str] = None      # resolved Skill scope (echo-only)

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
    existence of a Studio isn't leaked to non-members (mirrors studio_sources).
    """
    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        raise AppError.not_found("studio.not_found", "Studio not found")
    if editor and role not in _EDITOR_ROLES:
        raise AppError.forbidden(
            ErrorCode.ACCESS_DENIED, "Editor or owner role required"
        )
    return role


@router.get("/studios/{studio_id}/skills", response_model=List[StudioSkillRead])
async def list_studio_skills(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List the Skills pinned to a Studio (viewer+)."""
    _require_flag()
    await _require_role(db, studio_id, current_user)

    res = await db.execute(
        select(StudioSkill)
        .where(
            StudioSkill.studio_id == studio_id,
            StudioSkill.deleted_at.is_(None),
        )
        .order_by(StudioSkill.created_at.asc())
    )
    pins = list(res.scalars().all())
    if not pins:
        return []

    # Resolve Skill display fields (org-scoped visibility) in a single query.
    from app.models.skill import Skill

    skill_ids = [p.skill_id for p in pins]
    sk_res = await db.execute(
        select(Skill).where(
            Skill.id.in_(skill_ids),
            Skill.organization_id == organization.id,
        )
    )
    sk_by_id = {str(s.id): s for s in sk_res.scalars().all()}

    out: List[StudioSkillRead] = []
    for p in pins:
        sk = sk_by_id.get(str(p.skill_id))
        out.append(
            StudioSkillRead(
                id=str(p.id),
                studio_id=str(p.studio_id),
                skill_id=str(p.skill_id),
                name=getattr(sk, "name", None) if sk is not None else None,
                description=getattr(sk, "description", None) if sk is not None else None,
                scope=getattr(sk, "scope", None) if sk is not None else None,
            )
        )
    return out


@router.post("/studios/{studio_id}/skills", response_model=StudioSkillRead)
async def pin_studio_skill(
    studio_id: str,
    body: StudioSkillPin,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Pin a Skill to a Studio (editor+). Idempotent (deduped)."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    # The pinned skill must be a Skill the caller's org actually owns.
    from app.models.skill import Skill

    sk_res = await db.execute(
        select(Skill).where(
            Skill.id == body.skill_id,
            Skill.organization_id == organization.id,
        )
    )
    sk = sk_res.scalar_one_or_none()
    if sk is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Skill not found")

    # Dedupe: a (studio, skill) pin is unique. Return the existing row.
    existing_res = await db.execute(
        select(StudioSkill).where(
            StudioSkill.studio_id == studio_id,
            StudioSkill.skill_id == body.skill_id,
            StudioSkill.deleted_at.is_(None),
        )
    )
    pin = existing_res.scalar_one_or_none()
    if pin is None:
        pin = StudioSkill(studio_id=studio_id, skill_id=body.skill_id)
        db.add(pin)
        await db.commit()
        await db.refresh(pin)

    return StudioSkillRead(
        id=str(pin.id),
        studio_id=str(pin.studio_id),
        skill_id=str(pin.skill_id),
        name=getattr(sk, "name", None),
        description=getattr(sk, "description", None),
        scope=getattr(sk, "scope", None),
    )


@router.delete("/studios/{studio_id}/skills/{skill_id}")
async def unpin_studio_skill(
    studio_id: str,
    skill_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Unpin a Skill from a Studio (editor+). Soft-deletes the join row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    res = await db.execute(
        select(StudioSkill).where(
            StudioSkill.studio_id == studio_id,
            StudioSkill.skill_id == skill_id,
            StudioSkill.deleted_at.is_(None),
        )
    )
    pin = res.scalar_one_or_none()
    if pin is None:
        raise AppError.not_found("studio.skill_not_found", "Studio skill not found")

    # Soft-delete (matches resolve_studio_access / list filtering on deleted_at).
    pin.deleted_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "studio_id": studio_id, "skill_id": skill_id}
