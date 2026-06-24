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
enabled), so a fresh deploy behaves exactly like upstream dash.

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


class OptimizeSkillRequest(BaseModel):
    eval_suite_id: str | None = None
    case_ids: List[str] | None = None
    epochs: int = 3
    max_edits_per_epoch: int = 3


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
        "origin": getattr(skill, "origin", "manual") or "manual",
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
        origin="manual",
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
# OPTIMIZE: run the skill optimizer (Voyager/GEPA-style eval-driven SKILL.md
# refinement). Flag-gated by flags.SKILL_OPTIMIZE; never 500s on optimizer
# failure (returns {"error": ...} with HTTP 200). The optimizer module is
# imported LAZILY inside the handler so a missing/edited module never breaks
# import of this router.
# --------------------------------------------------------------------------- #
@router.post("/skills/{skill_id}/optimize")
async def optimize_skill_route(
    skill_id: str,
    payload: OptimizeSkillRequest | None = None,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Optimize a skill's SKILL.md against an eval suite (gated, never raises).

    Flag gate FIRST: when ``flags.SKILL_OPTIMIZE`` is OFF this returns
    ``{"disabled": True}`` (HTTP 200) BEFORE any heavy work. Otherwise it lazily
    imports + calls ``app.ai.skills.optimizer.optimize_skill`` and returns its
    summary dict. Any optimizer failure is wrapped to ``{"error": str(e)}`` with
    HTTP 200 — this endpoint never 500s.
    """
    # Flag gate FIRST — before SKILLS enable-check or any DB/LLM work.
    from app.settings.hybrid_flags import flags

    if not flags.SKILL_OPTIMIZE:
        return {"disabled": True}

    _ensure_enabled()

    req = payload or OptimizeSkillRequest()
    try:
        from app.ai.skills.optimizer import optimize_skill

        return await optimize_skill(
            db,
            organization=organization,
            user=current_user,
            skill_id=skill_id,
            eval_suite_id=req.eval_suite_id,
            case_ids=req.case_ids,
            epochs=req.epochs,
            max_edits_per_epoch=req.max_edits_per_epoch,
        )
    except Exception as e:  # never 500 on optimizer failure
        return {"error": str(e)}


# --------------------------------------------------------------------------- #
# ACTIVATE: promote a draft (e.g. optimizer-produced) skill to status='active'.
# BEFORE the flip, supersede any prior active version of the SAME logical key
# (org, scope, name) so the partial-unique index uq_skill_current
# (WHERE invalid_at IS NULL AND status='active') is never violated and the
# version timeline stays clean. Owner or org admin only.
# --------------------------------------------------------------------------- #
@router.post("/skills/{skill_id}/activate")
async def activate_skill(
    skill_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Activate a skill (status -> 'active'). Owner or org admin only.

    When ``flags.SKILL_OPTIMIZE`` is on, this first runs an INLINE supersede of
    any prior current active version of the same ``(organization_id, scope,
    name)`` (sets ``invalid_at`` + ``superseded_by`` on the old row) so the new
    active version does not collide with the ``uq_skill_current`` partial-unique
    index. The supersede is intentionally NOT routed through
    ``bitemporal.supersede_prior`` (which is gated on ``flags.BITEMPORAL``) —
    the partial index requires the supersede REGARDLESS of HYBRID_BITEMPORAL, so
    it is written inline and gated on ``flags.SKILL_OPTIMIZE``.
    """
    _ensure_enabled()

    skill = await _load_owned_skill(db, skill_id, organization)
    if skill is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Skill not found.")

    is_owner = str(skill.owner_user_id or "") == str(current_user.id)
    if not is_owner and not await _is_admin(db, current_user, organization):
        raise AppError.forbidden(message="Only the owner or an admin may activate this skill.")

    from app.settings.hybrid_flags import flags

    # Supersede the PRIOR current active version of the same (org, scope, name)
    # BEFORE flipping this row to active, so the two never coexist at commit
    # time and collide on uq_skill_current. Gated on flags.SKILL_OPTIMIZE (NOT
    # on the bitemporal flag — the partial index demands this regardless). Cols
    # are TIMESTAMP WITHOUT TIME ZONE -> use NAIVE UTC.
    if flags.SKILL_OPTIMIZE:
        from datetime import datetime, timezone
        from sqlalchemy import update
        from app.models.skill import Skill

        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.execute(
            update(Skill)
            .where(
                Skill.organization_id == skill.organization_id,
                Skill.scope == skill.scope,
                Skill.name == skill.name,
                Skill.id != skill.id,
                Skill.invalid_at.is_(None),
                Skill.status == "active",
            )
            .values(invalid_at=now_naive, superseded_by=str(skill.id))
        )

    skill.status = "active"
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
