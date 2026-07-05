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

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import Studio, StudioMember


# Role precedence so the *strongest* group grant wins when a user is in several
# granted groups. A group grant is at most "editor" — group sharing never
# confers ownership.
_ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


def _perms_to_role(permissions) -> str:
    """Map a ResourceGrant.permissions JSON list to a Studio role.

    'write'/'edit'/'manage' anywhere in the list -> editor, otherwise viewer.
    """
    perms = {str(p).lower() for p in (permissions or [])}
    if perms & {"write", "edit", "manage"}:
        return "editor"
    return "viewer"


async def user_group_ids(db: AsyncSession, user) -> List[str]:
    """Return the ids of every (non-deleted) group the user belongs to.

    Includes AD/LDAP/OIDC-synced groups — they are ordinary Group rows whose
    membership the sync service maintains. Used by both the single-studio
    resolver and the /studios list query.
    """
    uid = getattr(user, "id", None)
    if uid is None:
        return []
    from app.models.group_membership import GroupMembership

    rows = await db.execute(
        select(GroupMembership.group_id).where(
            GroupMembership.user_id == str(uid),
            GroupMembership.deleted_at.is_(None),
        )
    )
    return [r[0] for r in rows.all()]


async def group_granted_studio_roles(db: AsyncSession, user) -> dict:
    """Return {studio_id: role} for every studio shared to one of the user's
    groups via ResourceGrant(resource_type='studio', principal_type='group').

    Strongest grant wins per studio. Empty dict when the GROUP_ACCESS flag is
    off or the user is in no granted group. Flag is read here so callers stay
    simple and a flag flip is global.
    """
    from app.settings.hybrid_flags import flags

    if not flags.GROUP_ACCESS:
        return {}
    gids = await user_group_ids(db, user)
    if not gids:
        return {}

    from app.models.resource_grant import ResourceGrant

    rows = await db.execute(
        select(ResourceGrant.resource_id, ResourceGrant.permissions).where(
            ResourceGrant.resource_type == "studio",
            ResourceGrant.principal_type == "group",
            ResourceGrant.principal_id.in_(gids),
            ResourceGrant.deleted_at.is_(None),
        )
    )
    out: dict = {}
    for resource_id, permissions in rows.all():
        role = _perms_to_role(permissions)
        cur = out.get(str(resource_id))
        if cur is None or _ROLE_RANK[role] > _ROLE_RANK[cur]:
            out[str(resource_id)] = role
    return out


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

    # 2.5 Group grant (HYBRID_GROUP_ACCESS). A studio shared to one of the
    # user's groups (incl. AD/LDAP-synced) resolves to viewer/editor. No-op when
    # the flag is off. Checked before org-scope so an explicit group grant can
    # raise a user above plain org-viewer (e.g. editor).
    group_roles = await group_granted_studio_roles(db, user)
    granted = group_roles.get(str(studio_id))
    if granted:
        return granted

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


async def studio_chat_gate(db: AsyncSession, studio_id: str, user) -> bool:
    """Chat-time access gate for a report that carries a ``studio_id``.

    Returns True = allow chat, False = deny (403). Unlike ``resolve_studio_access``
    this tolerates a *stale* ``studio_id``: a report can outlive its Studio (soft-
    deleted), in which case chat must fall back to plain data-agent behaviour rather
    than 403 the org owner/admin.

    Logic:
        1. Raw Studio lookup (NO ``deleted_at`` filter). Missing OR soft-deleted
           studio -> the report has outlived its studio -> allow (do not gate).
        2. Org full-admin (or superuser) -> allow.
        3. Otherwise defer to ``resolve_studio_access`` (role is not None).
    """
    if user is None:
        return False

    # 1. Raw lookup — bypass the deleted_at filter used by resolve_studio_access.
    result = await db.execute(select(Studio).where(Studio.id == studio_id))
    studio = result.scalar_one_or_none()
    if studio is None or getattr(studio, "deleted_at", None) is not None:
        # Report outlived its studio -> treat as plain data-agent chat, do not gate.
        return True

    # 2. Full-admin / superuser always allowed.
    if getattr(user, "is_superuser", False):
        return True
    try:
        from app.core.permission_resolver import resolve_permissions, FULL_ADMIN

        resolved = await resolve_permissions(
            db, str(user.id), str(getattr(user, "organization_id", "") or "")
        )
        if FULL_ADMIN in resolved.org_permissions:
            return True
    except Exception:
        pass

    # 3. Fall back to the normal role resolver.
    role = await resolve_studio_access(db, studio_id, user)
    return role is not None
