from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from fastapi import HTTPException

from app.dependencies import get_async_db, get_current_organization
from app.models.user import User
from app.models.organization import Organization
from app.models.resource_grant import ResourceGrant
from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.core.permission_resolver import resolve_permissions, FULL_ADMIN
from sqlalchemy import select
from app.ee.license import require_enterprise
from app.services.rbac_service import rbac_service
from app.schemas.rbac_schema import (
    RoleCreate, RoleUpdate, RoleSchema,
    GroupCreate, GroupUpdate, GroupSchema, GroupMemberAdd, GroupMemberSchema,
    RoleAssignmentCreate, RoleAssignmentSchema,
    ResourceGrantCreate, ResourceGrantUpdate, ResourceGrantSchema,
)

router = APIRouter(tags=["rbac"])


# ── Permission Registry ──────────────────────────────────────────────────

@router.get("/permissions/registry")
async def get_permissions_registry(current_user: User = Depends(current_user)):
    """Returns all available permission categories and resource permission options."""
    from app.core.permissions_registry import (
        PERMISSION_CATEGORIES, RESOURCE_PERMISSIONS,
        MERGED_CATEGORIES, RESOURCE_SCOPED_GROUPS,
        CONNECTION_RESOURCE_PERMISSIONS,
    )
    from app.settings.hybrid_flags import flags

    resource_permissions = RESOURCE_PERMISSIONS
    resource_scoped_groups = RESOURCE_SCOPED_GROUPS
    # #489 (flag CONNECTION_GRANTS): surface per-connection grant options in the
    # role editor only when enabled. OFF → identical to the pre-#489 registry.
    if flags.CONNECTION_GRANTS:
        resource_permissions = {
            **RESOURCE_PERMISSIONS,
            "connection": list(CONNECTION_RESOURCE_PERMISSIONS),
        }
        resource_scoped_groups = {
            **RESOURCE_SCOPED_GROUPS,
            "connection": {"Permissions": list(CONNECTION_RESOURCE_PERMISSIONS)},
        }
    return {
        "categories": PERMISSION_CATEGORIES,
        "resource_permissions": resource_permissions,
        "merged_categories": MERGED_CATEGORIES,
        "resource_scoped_groups": resource_scoped_groups,
    }


# ── Roles ────────────────────────────────────────────────────────────────

@router.get("/organizations/{organization_id}/roles", response_model=List[RoleSchema])
@requires_permission("view_members")
async def list_roles(
    organization_id: str,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.list_roles(db, organization_id)


@router.post("/organizations/{organization_id}/roles", response_model=RoleSchema)
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def create_role(
    organization_id: str,
    data: RoleCreate,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.create_role(db, organization_id, data)


@router.put("/organizations/{organization_id}/roles/{role_id}", response_model=RoleSchema)
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def update_role(
    organization_id: str,
    role_id: str,
    data: RoleUpdate,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.update_role(db, organization_id, role_id, data)


@router.delete("/organizations/{organization_id}/roles/{role_id}", status_code=204)
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def delete_role(
    organization_id: str,
    role_id: str,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await rbac_service.delete_role(db, organization_id, role_id)


# ── Groups ───────────────────────────────────────────────────────────────

@router.get("/organizations/{organization_id}/groups", response_model=List[GroupSchema])
@require_enterprise(feature="custom_roles")
@requires_permission("view_members")
async def list_groups(
    organization_id: str,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.list_groups(db, organization_id)


@router.post("/organizations/{organization_id}/groups", response_model=GroupSchema)
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def create_group(
    organization_id: str,
    data: GroupCreate,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.create_group(db, organization_id, data)


@router.put("/organizations/{organization_id}/groups/{group_id}", response_model=GroupSchema)
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def update_group(
    organization_id: str,
    group_id: str,
    data: GroupUpdate,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.update_group(db, organization_id, group_id, data)


@router.delete("/organizations/{organization_id}/groups/{group_id}", status_code=204)
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def delete_group(
    organization_id: str,
    group_id: str,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await rbac_service.delete_group(db, organization_id, group_id)


@router.get("/organizations/{organization_id}/groups/{group_id}/members", response_model=List[GroupMemberSchema])
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def list_group_members(
    organization_id: str,
    group_id: str,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.list_group_members(db, organization_id, group_id)


@router.post("/organizations/{organization_id}/groups/{group_id}/members", status_code=201)
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def add_group_member(
    organization_id: str,
    group_id: str,
    data: GroupMemberAdd,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await rbac_service.add_group_member(
        db, organization_id, group_id,
        user_id=data.user_id, membership_id=data.membership_id,
    )


@router.delete("/organizations/{organization_id}/groups/{group_id}/members/{principal_id}", status_code=204)
@require_enterprise(feature="custom_roles")
@requires_permission("manage_members")
async def remove_group_member(
    organization_id: str,
    group_id: str,
    principal_id: str,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await rbac_service.remove_group_member(db, organization_id, group_id, principal_id)


# ── Role Assignments ─────────────────────────────────────────────────────

@router.get("/organizations/{organization_id}/role-assignments", response_model=List[RoleAssignmentSchema])
@requires_permission("view_members")
async def list_role_assignments(
    organization_id: str,
    principal_type: Optional[str] = Query(None),
    principal_id: Optional[str] = Query(None),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.list_role_assignments(db, organization_id, principal_type, principal_id)


@router.post("/organizations/{organization_id}/role-assignments", response_model=RoleAssignmentSchema)
@requires_permission("manage_members")
async def create_role_assignment(
    organization_id: str,
    data: RoleAssignmentCreate,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.create_role_assignment(db, organization_id, data)


@router.delete("/organizations/{organization_id}/role-assignments/{assignment_id}", status_code=204)
@requires_permission("manage_members")
async def delete_role_assignment(
    organization_id: str,
    assignment_id: str,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await rbac_service.delete_role_assignment(db, organization_id, assignment_id)


# ── Resource Grants ──────────────────────────────────────────────────────

async def _require_resource_manage(
    db: AsyncSession, user: User, org_id: str, resource_type: str, resource_id: str
) -> None:
    """Authorize a resource-grant mutation: caller must hold `manage` on the
    target resource (or be a full org admin). Org-level `manage_members` is
    deliberately NOT sufficient — granting per-resource access requires
    per-resource authority.
    """
    from app.models.membership import Membership
    stmt = select(Membership).where(
        Membership.user_id == user.id,
        Membership.organization_id == org_id,
    )
    result = await db.execute(stmt)
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="User is not a member of this organization")

    resolved = await resolve_permissions(db, str(user.id), str(org_id))
    if FULL_ADMIN in resolved.org_permissions:
        return
    # #489: the owner-level permission differs by resource type — `manage_connection`
    # on a connection, `manage` on an agent. Flag OFF → always `manage`
    # (byte-identical to the pre-#489 fork).
    from app.settings.hybrid_flags import flags
    owner_perm = (
        "manage_connection"
        if (resource_type == "connection" and flags.CONNECTION_GRANTS)
        else "manage"
    )
    if resolved.has_resource_permission(resource_type, str(resource_id), owner_perm):
        return
    raise HTTPException(
        status_code=403,
        detail=f"Requires '{owner_perm}' on {resource_type} {resource_id}",
    )




@router.get("/organizations/{organization_id}/resource-grants", response_model=List[ResourceGrantSchema])
@requires_permission("view_members")
async def list_resource_grants(
    organization_id: str,
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    principal_type: Optional[str] = Query(None),
    principal_id: Optional[str] = Query(None),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await rbac_service.list_resource_grants(
        db, organization_id, resource_type, resource_id, principal_type, principal_id
    )


@router.post("/organizations/{organization_id}/resource-grants", response_model=ResourceGrantSchema)
async def create_resource_grant(
    organization_id: str,
    data: ResourceGrantCreate,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await _require_resource_manage(
        db, current_user, organization_id, data.resource_type, data.resource_id
    )
    # NON-SHAREABLE: a private (per-agent) connector — or a data source backed
    # by one — can never be granted to another principal. No-op for org
    # connectors / unrelated resource types.
    await _deny_share_private_connector(db, data.resource_type, data.resource_id)
    return await rbac_service.create_resource_grant(db, organization_id, data)


async def _deny_share_private_connector(
    db: AsyncSession, resource_type: str, resource_id: str
) -> None:
    """Raise 403 if `resource_type`/`resource_id` points at a private connector
    (or a data source wrapping one). Inert for org connectors and other types.
    """
    from sqlalchemy.orm import selectinload
    from app.services import private_connector_guard as _pcg
    from app.models.connection import Connection

    if resource_type == "connection":
        conn = (
            await db.execute(select(Connection).where(Connection.id == resource_id))
        ).scalar_one_or_none()
        if conn is not None:
            _pcg.deny_share(conn)
    elif resource_type == "data_source":
        from app.models.data_source import DataSource
        ds = (
            await db.execute(
                select(DataSource)
                .options(selectinload(DataSource.connections))
                .where(DataSource.id == resource_id)
            )
        ).scalar_one_or_none()
        if ds is not None:
            await _pcg.deny_share_data_source(db, ds)


async def _load_grant_or_404(db: AsyncSession, org_id: str, grant_id: str) -> ResourceGrant:
    result = await db.execute(
        select(ResourceGrant).where(
            ResourceGrant.id == grant_id,
            ResourceGrant.organization_id == org_id,
            ResourceGrant.deleted_at.is_(None),
        )
    )
    grant = result.scalar_one_or_none()
    if not grant:
        raise HTTPException(status_code=404, detail="Resource grant not found")
    return grant


@router.put("/organizations/{organization_id}/resource-grants/{grant_id}", response_model=ResourceGrantSchema)
async def update_resource_grant(
    organization_id: str,
    grant_id: str,
    data: ResourceGrantUpdate,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    grant = await _load_grant_or_404(db, organization_id, grant_id)
    await _require_resource_manage(
        db, current_user, organization_id, grant.resource_type, grant.resource_id
    )
    return await rbac_service.update_resource_grant(db, organization_id, grant_id, data)


@router.delete("/organizations/{organization_id}/resource-grants/{grant_id}", status_code=204)
async def delete_resource_grant(
    organization_id: str,
    grant_id: str,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    grant = await _load_grant_or_404(db, organization_id, grant_id)
    await _require_resource_manage(
        db, current_user, organization_id, grant.resource_type, grant.resource_id
    )
    await rbac_service.delete_resource_grant(db, organization_id, grant_id)
