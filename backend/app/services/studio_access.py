"""Studio access resolution (hybrid Studios ST1).

Thin permission helper checked on every studio route. Returns the *effective*
role a user holds on a Studio, or None when the user has no access.

Resolution order (most specific first):
    1. owner_user_id == user.id                       -> 'owner'
    2. explicit StudioMember row for this user        -> its role
    3. share_scope == 'org' and same organization     -> 'viewer'
    4. otherwise                                      -> None

This module is import-safe regardless of flags.STUDIOS (no flag read here — the
flag is enforced at the route layer); it only performs DB lookups.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import Studio, StudioMember


async def resolve_studio_access(
    db: AsyncSession,
    studio_id: str,
    user,
) -> Optional[str]:
    """Return the effective role ('owner'|'editor'|'viewer') or None.

    Args:
        db: async session.
        studio_id: the Studio id.
        user: the authenticated User (must expose .id and .organization_id, or
            be resolvable to an org via membership upstream — here we read
            user.organization_id if present).
    """
    if user is None:
        return None

    result = await db.execute(
        select(Studio).where(
            Studio.id == studio_id,
            Studio.deleted_at.is_(None),
        )
    )
    studio = result.scalar_one_or_none()
    if studio is None:
        return None

    # 1. Owner.
    if studio.owner_user_id == getattr(user, "id", None):
        return "owner"

    # 2. Explicit member row.
    member_result = await db.execute(
        select(StudioMember).where(
            StudioMember.studio_id == studio_id,
            StudioMember.user_id == getattr(user, "id", None),
            StudioMember.deleted_at.is_(None),
        )
    )
    member = member_result.scalar_one_or_none()
    if member is not None and member.role:
        return member.role

    # 3. Org-shared -> viewer for any member of the same org.
    user_org_id = getattr(user, "organization_id", None)
    if (
        studio.share_scope == "org"
        and user_org_id is not None
        and studio.organization_id == user_org_id
    ):
        return "viewer"

    # 4. No access.
    return None
