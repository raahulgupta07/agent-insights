"""
Studio routes (hybrid Studios ST1/ST3 — CRUD + members + sharing)
==================================================================

NotebookLM-style shareable agent container. A Studio wraps existing Data
Agents (DataSource) as pinned sources, plus a persona, members/roles and
sharing scope. This module owns Studio CRUD, member management and the
share-scope toggle. Sibling agents own pinned sources / artifacts / skills
(``studio_sources.py`` / ``studio_artifacts.py`` / ``studio_skills.py``).

Mirrors the route conventions in ``app.routes.skill`` (deps, auth,
AppError/ErrorCode, no ``/api`` prefix — main.py adds it).

Gating (CLAUDE.md HARD RULE 4): every endpoint is gated by ``flags.STUDIOS``
(env ``HYBRID_STUDIOS``, default OFF). When the flag is off, ``GET /studios``
returns ``[]`` and every other endpoint raises AppError 404 (feature not
enabled), so a fresh deploy behaves exactly like upstream bow.

Access (ST3): every route resolves the caller's effective role via
``resolve_studio_access`` (owner > member > org-viewer > None) and enforces
the role matrix — viewer: read/chat; editor: + edit config; owner: + manage
members / delete / share.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.organization import Organization
from app.models.user import User
from app.schemas.studio import (
    StudioCreate,
    StudioMemberResponse,
    StudioResponse,
    StudioUpdate,
)
from app.services.studio_access import resolve_studio_access

router = APIRouter(tags=["studios"])

_EDITOR_ROLES = {"owner", "editor"}


def _ensure_enabled() -> None:
    """Raise 404 (feature not enabled) unless flags.STUDIOS is on."""
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS:
        raise AppError(
            ErrorCode.FEATURE_LOCKED,
            "Studios are not enabled.",
            status_code=404,
        )


def _serialize(studio) -> dict:
    return {
        "id": str(studio.id),
        "name": studio.name,
        "description": studio.description,
        "persona": studio.persona,
        "avatar": studio.avatar,
        "owner_user_id": str(studio.owner_user_id),
        "organization_id": str(studio.organization_id),
        "share_scope": studio.share_scope,
        "share_token": studio.share_token,
        "config": studio.config or {},
        "created_at": studio.created_at,
        "updated_at": studio.updated_at,
    }


def _serialize_member(member, *, user: Optional[User] = None) -> dict:
    return {
        "id": str(member.id),
        "studio_id": str(member.studio_id),
        "user_id": str(member.user_id),
        "role": member.role,
        "user_name": getattr(user, "name", None) if user is not None else None,
        "user_email": getattr(user, "email", None) if user is not None else None,
        "created_at": member.created_at,
        "updated_at": member.updated_at,
    }


async def _load_studio(db: AsyncSession, studio_id: str):
    """Load a non-deleted Studio by id, or None."""
    from app.models.studio import Studio

    result = await db.execute(
        select(Studio).where(
            Studio.id == studio_id,
            Studio.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _require_access(
    db: AsyncSession, studio_id: str, user: User, *, minimum: str
) -> tuple:
    """Load the studio + caller role, enforcing a minimum role.

    minimum is one of 'viewer' | 'editor' | 'owner'. Raises 404 when the
    studio does not exist, 403 when it exists but the caller has no access or
    holds a role below the minimum.
    """
    studio = await _load_studio(db, studio_id)
    if studio is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Studio not found.")

    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        raise AppError.forbidden(message="You do not have access to this studio.")

    if minimum == "owner" and role != "owner":
        raise AppError.forbidden(message="Only the owner may perform this action.")
    if minimum == "editor" and role not in _EDITOR_ROLES:
        raise AppError.forbidden(message="Editor access is required.")

    return studio, role


# --------------------------------------------------------------------------- #
# CREATE
# --------------------------------------------------------------------------- #
@router.post("/studios", response_model=StudioResponse)
async def create_studio(
    payload: StudioCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Create a Studio owned by the caller (also seeds an owner member row)."""
    _ensure_enabled()

    from app.models.studio import Studio, StudioMember

    studio = Studio(
        name=payload.name,
        description=payload.description,
        persona=payload.persona,
        avatar=payload.avatar,
        owner_user_id=str(current_user.id),
        organization_id=str(organization.id),
        share_scope=payload.share_scope.value,
        config=payload.config or {},
    )
    db.add(studio)
    await db.flush()  # assign studio.id before the member row references it

    db.add(
        StudioMember(
            studio_id=str(studio.id),
            user_id=str(current_user.id),
            role="owner",
        )
    )
    await db.commit()
    await db.refresh(studio)
    return _serialize(studio)


# --------------------------------------------------------------------------- #
# LIST (owned ∪ member ∪ org-scope)
# --------------------------------------------------------------------------- #
@router.get("/studios", response_model=List[StudioResponse])
async def list_studios(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> List[dict]:
    """List studios the caller can access. [] when the flag is off."""
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS:
        return []

    from app.models.studio import Studio, StudioMember

    org_id = str(organization.id)
    uid = str(current_user.id)

    # member studio ids for this user
    member_ids_result = await db.execute(
        select(StudioMember.studio_id).where(
            StudioMember.user_id == uid,
            StudioMember.deleted_at.is_(None),
        )
    )
    member_ids = [row[0] for row in member_ids_result.all()]

    visible = or_(
        Studio.owner_user_id == uid,
        Studio.share_scope == "org",
    )
    if member_ids:
        visible = or_(visible, Studio.id.in_(member_ids))

    result = await db.execute(
        select(Studio)
        .where(
            Studio.organization_id == org_id,
            Studio.deleted_at.is_(None),
            visible,
        )
        .order_by(Studio.created_at.desc())
    )
    studios = result.scalars().all()
    return [_serialize(s) for s in studios]


# --------------------------------------------------------------------------- #
# GET one
# --------------------------------------------------------------------------- #
@router.get("/studios/{studio_id}", response_model=StudioResponse)
async def get_studio(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Load a single Studio. 404 when not found or the caller has no access."""
    _ensure_enabled()

    studio, _role = await _require_access(db, studio_id, current_user, minimum="viewer")
    return _serialize(studio)


# --------------------------------------------------------------------------- #
# UPDATE (editor+)
# --------------------------------------------------------------------------- #
@router.patch("/studios/{studio_id}", response_model=StudioResponse)
async def update_studio(
    studio_id: str,
    payload: StudioUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Edit a Studio's name/description/persona/avatar/config (editor+).

    share_scope is intentionally NOT mutated here — use PATCH /share (owner).
    """
    _ensure_enabled()

    studio, _role = await _require_access(db, studio_id, current_user, minimum="editor")

    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "description", "persona", "avatar", "config"):
        if field in data:
            setattr(studio, field, data[field])

    await db.commit()
    await db.refresh(studio)
    return _serialize(studio)


# --------------------------------------------------------------------------- #
# DELETE (owner only, soft-delete)
# --------------------------------------------------------------------------- #
@router.delete("/studios/{studio_id}")
async def delete_studio(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Soft-delete a Studio (set deleted_at). Owner only."""
    _ensure_enabled()

    studio, _role = await _require_access(db, studio_id, current_user, minimum="owner")

    studio.deleted_at = datetime.utcnow()
    await db.commit()
    return {"id": str(studio_id), "deleted": True}


# --------------------------------------------------------------------------- #
# MEMBERS: list
# --------------------------------------------------------------------------- #
@router.get("/studios/{studio_id}/members", response_model=List[StudioMemberResponse])
async def list_members(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> List[dict]:
    """List a Studio's explicit member rows (viewer+ may read)."""
    _ensure_enabled()

    await _require_access(db, studio_id, current_user, minimum="viewer")

    from app.models.studio import StudioMember

    result = await db.execute(
        select(StudioMember).where(
            StudioMember.studio_id == studio_id,
            StudioMember.deleted_at.is_(None),
        )
    )
    members = result.scalars().all()

    # Resolve display name/email per member (echo-only).
    user_ids = [str(m.user_id) for m in members]
    users_by_id: dict = {}
    if user_ids:
        urows = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_by_id = {str(u.id): u for u in urows.scalars().all()}

    return [
        _serialize_member(m, user=users_by_id.get(str(m.user_id))) for m in members
    ]


# --------------------------------------------------------------------------- #
# MEMBERS: invite by email (owner)
# --------------------------------------------------------------------------- #
class MemberInviteRequest(BaseModel):
    email: str
    role: str = "viewer"


class MemberRoleRequest(BaseModel):
    role: str


def _validate_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role not in {"owner", "editor", "viewer"}:
        raise AppError.bad_request(
            ErrorCode.VALIDATION, "role must be owner|editor|viewer."
        )
    return role


@router.post("/studios/{studio_id}/members", response_model=StudioMemberResponse)
async def add_member(
    studio_id: str,
    payload: MemberInviteRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Invite a user (by email, same org) to the Studio (owner only)."""
    _ensure_enabled()

    await _require_access(db, studio_id, current_user, minimum="owner")
    role = _validate_role(payload.role)

    email = (payload.email or "").strip().lower()
    if not email:
        raise AppError.bad_request(ErrorCode.VALIDATION, "email is required.")

    # Look up a user with this email who is a member of THIS org.
    from app.models.membership import Membership
    from app.models.studio import StudioMember

    user_result = await db.execute(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(
            User.email == email,
            Membership.organization_id == str(organization.id),
        )
        .limit(1)
    )
    target = user_result.scalar_one_or_none()
    if target is None:
        raise AppError.not_found(
            ErrorCode.ENTITY_NOT_FOUND, "No user with that email in this organization."
        )

    # Reuse an existing (non-deleted) row if present → idempotent role update.
    existing_result = await db.execute(
        select(StudioMember).where(
            StudioMember.studio_id == studio_id,
            StudioMember.user_id == str(target.id),
            StudioMember.deleted_at.is_(None),
        )
    )
    member = existing_result.scalar_one_or_none()
    if member is not None:
        member.role = role
    else:
        member = StudioMember(
            studio_id=studio_id,
            user_id=str(target.id),
            role=role,
        )
        db.add(member)

    await db.commit()
    await db.refresh(member)
    return _serialize_member(member, user=target)


# --------------------------------------------------------------------------- #
# MEMBERS: change role (owner)
# --------------------------------------------------------------------------- #
@router.patch(
    "/studios/{studio_id}/members/{user_id}", response_model=StudioMemberResponse
)
async def update_member(
    studio_id: str,
    user_id: str,
    payload: MemberRoleRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Change a member's role (owner only)."""
    _ensure_enabled()

    studio, _role = await _require_access(db, studio_id, current_user, minimum="owner")
    role = _validate_role(payload.role)

    from app.models.studio import StudioMember

    result = await db.execute(
        select(StudioMember).where(
            StudioMember.studio_id == studio_id,
            StudioMember.user_id == user_id,
            StudioMember.deleted_at.is_(None),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Member not found.")

    member.role = role
    await db.commit()
    await db.refresh(member)

    urow = await db.execute(select(User).where(User.id == user_id))
    return _serialize_member(member, user=urow.scalar_one_or_none())


# --------------------------------------------------------------------------- #
# MEMBERS: remove (owner)
# --------------------------------------------------------------------------- #
@router.delete("/studios/{studio_id}/members/{user_id}")
async def remove_member(
    studio_id: str,
    user_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Remove a member from the Studio (owner only, soft-delete).

    The owner's own implicit membership cannot be removed here — removing the
    owner member row would orphan the studio's owner record.
    """
    _ensure_enabled()

    studio, _role = await _require_access(db, studio_id, current_user, minimum="owner")

    if str(user_id) == str(studio.owner_user_id):
        raise AppError.bad_request(
            ErrorCode.VALIDATION, "The studio owner cannot be removed."
        )

    from app.models.studio import StudioMember

    result = await db.execute(
        select(StudioMember).where(
            StudioMember.studio_id == studio_id,
            StudioMember.user_id == user_id,
            StudioMember.deleted_at.is_(None),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Member not found.")

    member.deleted_at = datetime.utcnow()
    await db.commit()
    return {"studio_id": str(studio_id), "user_id": str(user_id), "removed": True}


# --------------------------------------------------------------------------- #
# SHARE: set scope + (de)generate share token (owner)
# --------------------------------------------------------------------------- #
class ShareRequest(BaseModel):
    share_scope: str
    # When None, a 'link' scope auto-generates a token; provide regenerate=True
    # to force a fresh token even if one already exists.
    regenerate: bool = False


@router.patch("/studios/{studio_id}/share", response_model=StudioResponse)
async def set_share(
    studio_id: str,
    payload: ShareRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Set a Studio's share scope (owner only).

    'private' / 'org' clear any share token. 'link' generates a token (stored
    only — public link serving is deferred to ST6 + a security review).
    """
    _ensure_enabled()

    studio, _role = await _require_access(db, studio_id, current_user, minimum="owner")

    scope = (payload.share_scope or "").strip().lower()
    if scope not in {"private", "org", "link"}:
        raise AppError.bad_request(
            ErrorCode.VALIDATION, "share_scope must be private|org|link."
        )

    studio.share_scope = scope
    if scope == "link":
        if not studio.share_token or payload.regenerate:
            studio.share_token = secrets.token_urlsafe(32)
    else:
        studio.share_token = None

    await db.commit()
    await db.refresh(studio)
    return _serialize(studio)
