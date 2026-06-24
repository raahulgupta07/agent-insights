"""
Skill routes (Phase 6 — self-service Skills authoring/read)
===========================================================

"Save as skill" authoring + progressive-disclosure reads. Mirrors the route
conventions in ``app.routes.instruction`` (deps, auth, AppError/ErrorCode,
no ``/api`` prefix — main.py adds it; router registered in main.py by the
parent agent).

Gating (CLAUDE.md HARD RULE 4): every endpoint is gated by ``flags.SKILLS``
(env ``HYBRID_SKILLS``, default OFF). When the flag is off, ``GET /skills``
returns ``[]`` and every other endpoint raises AppError 404 (feature not
enabled), so a fresh deploy behaves exactly like upstream bow.

Non-live (HARD RULE 5): authoring lands a PERSONAL skill at ``status='draft'``;
promotion flips scope personal->org and resets status to 'draft' so an admin
must still activate it (the approval gate). Nothing here writes status='active'.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List

from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.user import User
from app.models.organization import Organization
from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission

router = APIRouter(tags=["skills"])


class InvokeSkillRequest(BaseModel):
    arguments: str = ""


def _ensure_enabled() -> None:
    """Raise 404 (feature not enabled) unless flags.SKILLS is on."""
    from app.settings.hybrid_flags import flags

    if not flags.SKILLS:
        raise AppError(
            ErrorCode.FEATURE_LOCKED,
            "Skills are not enabled.",
            status_code=404,
        )


async def _is_admin(db: AsyncSession, user: User, organization: Organization) -> bool:
    """True when the user holds full_admin_access in this org. Degrades to False."""
    try:
        from app.core.permission_resolver import resolve_permissions, FULL_ADMIN

        resolved = await resolve_permissions(db, str(user.id), str(organization.id))
        return FULL_ADMIN in resolved.org_permissions
    except Exception:
        return False


async def _load_owned_skill(db: AsyncSession, skill_id: str, organization: Organization):
    """Load a non-deleted Skill scoped to this org by id, or None."""
    from sqlalchemy import select
    from app.models.skill import Skill

    stmt = (
        select(Skill)
        .where(
            Skill.id == skill_id,
            Skill.organization_id == str(organization.id),
            Skill.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


def _serialize(skill: Any) -> dict:
    return {
        "id": str(skill.id),
        "name": skill.name,
        "description": skill.description,
        "scope": skill.scope,
        "status": skill.status,
        "category": skill.category,
        "skill_md": skill.skill_md,
        "owner_user_id": str(skill.owner_user_id) if skill.owner_user_id else None,
    }


# --------------------------------------------------------------------------- #
# READ: L1 catalog
# --------------------------------------------------------------------------- #
@router.get("/skills")
async def list_skills(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> List[dict]:
    """List skills visible to this user (L1 catalog). [] when flag off."""
    from app.ai.skills.loader import list_visible_skills

    return await list_visible_skills(
        db,
        organization_id=str(organization.id),
        user_id=str(current_user.id),
    )


# --------------------------------------------------------------------------- #
# READ: full SKILL.md body (L2) by id
# --------------------------------------------------------------------------- #
@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Load a single skill (full body) by id, scoped to this org."""
    _ensure_enabled()

    skill = await _load_owned_skill(db, skill_id, organization)
    if skill is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Skill not found.")
    return _serialize(skill)


# --------------------------------------------------------------------------- #
# WRITE: author a DRAFT personal skill from a solved completion
# --------------------------------------------------------------------------- #
@router.post("/skills/from-completion/{completion_id}")
@requires_permission("create_reports")
async def create_skill_from_completion(
    completion_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Author a reusable SKILL.md draft from a solved completion.

    The new skill is PERSONAL + status='draft'. 404 if nothing was authored.
    """
    _ensure_enabled()

    from sqlalchemy import select
    from app.models.completion import Completion

    stmt = (
        select(Completion)
        .where(
            Completion.id == completion_id,
            Completion.report.has(organization_id=str(organization.id)),
        )
        .limit(1)
    )
    completion = (await db.execute(stmt)).scalars().first()
    if completion is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Completion not found.")

    # Resolve the org's small model for the one-shot authoring call.
    model = None
    try:
        from app.services.llm_service import LLMService

        model = await LLMService().get_default_model(
            db, organization, current_user, is_small=True
        )
    except Exception:
        model = None

    from app.services.skill_authoring import distill_skill_from_completion

    skill_id = await distill_skill_from_completion(
        db,
        completion=completion,
        user=current_user,
        organization=organization,
        model=model,
    )
    if not skill_id:
        raise AppError.not_found(
            ErrorCode.ENTITY_NOT_FOUND, "Could not author a skill from this completion."
        )

    skill = await _load_owned_skill(db, skill_id, organization)
    if skill is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Authored skill not found.")
    return _serialize(skill)


# --------------------------------------------------------------------------- #
# WRITE: promote a personal skill -> org scope (still draft = approval gate)
# --------------------------------------------------------------------------- #
@router.post("/skills/{skill_id}/promote")
async def promote_skill(
    skill_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Promote the caller's OWN personal skill to org scope.

    Sets scope='org' and resets status to 'draft' — org skills require an admin
    to activate them (the approval gate). Only the owner may promote.
    """
    _ensure_enabled()

    skill = await _load_owned_skill(db, skill_id, organization)
    if skill is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Skill not found.")

    if skill.scope != "personal":
        raise AppError.bad_request(
            ErrorCode.VALIDATION, "Only a personal skill can be promoted."
        )

    if str(skill.owner_user_id or "") != str(current_user.id):
        raise AppError.forbidden(message="Only the owner may promote this skill.")

    skill.scope = "org"
    skill.status = "draft"  # never auto-activate; admin must approve org skills
    await db.commit()
    await db.refresh(skill)
    return _serialize(skill)


# --------------------------------------------------------------------------- #
# INVOKE: resolve SKILL.md body + substitute args (explicit human-invoke path)
# --------------------------------------------------------------------------- #
@router.post("/skills/{skill_id}/invoke")
async def invoke_skill(
    skill_id: str,
    payload: InvokeSkillRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Explicit human-invoke of a skill (Claude-Code ``/skill`` path).

    Resolves the SKILL.md body (frontmatter stripped) and substitutes the
    caller's ``arguments`` into it. Works even for skills the model cannot
    auto-invoke. Returns the ready-to-run prompt; it does not execute anything.
    """
    _ensure_enabled()

    skill = await _load_owned_skill(db, skill_id, organization)
    if skill is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Skill not found.")

    # Honor user_invocable; treat None/missing as True (pre-migration rows).
    if getattr(skill, "user_invocable", True) is False:
        raise AppError.forbidden(message="This skill is not user-invocable.")

    arguments = payload.arguments or ""

    # Resolve body + substitute args; degrade to the raw SKILL.md best-effort.
    try:
        from app.ai.skills.frontmatter import parse_frontmatter
        from app.ai.skills.invocation import substitute_arguments

        fm, body = parse_frontmatter(skill.skill_md or "")
        prompt = substitute_arguments(body, arguments)
    except Exception:
        prompt = skill.skill_md or ""

    # Best-effort usage record (own session; never break the response).
    try:
        from app.ai.skills.loader import record_skill_use

        await record_skill_use(str(skill.id))
    except Exception:
        pass

    return {
        "id": str(skill.id),
        "name": skill.name,
        "prompt": prompt,
        "arguments": arguments,
    }


# --------------------------------------------------------------------------- #
# DELETE: soft-delete (owner or admin)
# --------------------------------------------------------------------------- #
@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Soft-delete a skill (set deleted_at). Owner or org admin only."""
    _ensure_enabled()

    skill = await _load_owned_skill(db, skill_id, organization)
    if skill is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Skill not found.")

    is_owner = str(skill.owner_user_id or "") == str(current_user.id)
    if not is_owner and not await _is_admin(db, current_user, organization):
        raise AppError.forbidden(message="Only the owner or an admin may delete this skill.")

    from datetime import datetime

    skill.deleted_at = datetime.utcnow()
    await db.commit()
    return {"id": str(skill_id), "deleted": True}
