"""
Connection Routes - Admin-only CRUD for database connections.
Connections are the underlying database connections that Domains (DataSources) link to.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.dependencies import get_async_db
from app.models.user import User
from app.core.auth import current_user
from app.models.organization import Organization
from app.models.datasource_table import DataSourceTable
from app.models.connection_table import ConnectionTable
from app.models.connection_tool import ConnectionTool
from app.models.data_source import DataSource
from app.dependencies import get_current_organization
from app.services.connection_service import ConnectionService
from app.core.permissions_decorator import requires_permission
from app.core.permission_resolver import resolve_permissions, FULL_ADMIN
from app.models.membership import Membership
from app.schemas.connection_schema import (
    ConnectionCreate,
    ConnectionUpdate,
    ConnectionSchema,
    ConnectionDetailSchema,
    ConnectionTableSchema,
    ConnectionTestOverride,
    ConnectionTestResult,
    ConnectionIndexingProgress,
)
from app.services.connection_indexing_service import ConnectionIndexingService
from app.schemas.connection_tool_schema import (
    ConnectionToolSchema,
    ConnectionToolUpdate,
    BatchToolUpdate,
)


import logging

router = APIRouter(prefix="/connections", tags=["connections"])
connection_service = ConnectionService()
indexing_service = ConnectionIndexingService()
logger = logging.getLogger(__name__)

# Valid 3-level connector visibility values (management-plane sharing model).
VALID_VISIBILITIES = {"private", "shared", "org"}


def _indexing_to_progress(row) -> "ConnectionIndexingProgress | None":
    """Adapt a ConnectionIndexing ORM row to the polling payload. Returns None
    when no row is provided.
    """
    if row is None:
        return None
    return ConnectionIndexingProgress(
        id=str(row.id),
        status=row.status,
        phase=row.phase,
        current_item=row.current_item,
        progress_done=row.progress_done or 0,
        progress_total=row.progress_total or 0,
        started_at=row.started_at.isoformat() if row.started_at else None,
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        error=row.error,
        stats=row.stats_json,
        events=row.events_json or [],
    )


async def _is_org_admin(db: AsyncSession, user: User, organization: Organization) -> bool:
    """Return True if user has admin-level connection/data source access in the org."""
    resolved = await resolve_permissions(db, str(user.id), str(organization.id))
    return (
        FULL_ADMIN in resolved.org_permissions
        or resolved.has_org_permission("manage_connections")
    )


async def _user_can_access_connection(
    db: AsyncSession, user: User, connection
) -> bool:
    """Non-admin accessibility check: user must have access to at least one linked data source."""
    from app.core.permission_resolver import user_can_access_data_source
    org_id = str(connection.organization_id) if getattr(connection, 'organization_id', None) else None
    for ds in (connection.data_sources or []):
        if getattr(ds, "is_public", False):
            return True
        if org_id and await user_can_access_data_source(db, str(user.id), org_id, ds):
            return True
    return False


async def _guard_private_owner(db, connection_id, organization, current_user):
    """OWNER-OR-ADMIN guard for managing a connection.

    Loads the connection and authorizes the caller to mutate it:
      * super admin / manage_connections → may manage ANY connection in the org
        (full super-admin override, incl. another user's private connector);
      * otherwise → the caller MUST be the connector's owner (owner_user_id ==
        caller). Org connectors (owner_user_id NULL) are admin-managed, so a
        non-admin is denied.
    Used by the mutate/test/reindex/tables routes so the check happens BEFORE
    any side effect. (Credentials are still never returned to the client.)
    """
    connection = await connection_service.get_connection(db, connection_id, organization)
    if await _is_org_admin(db, current_user, organization):
        return connection  # super-admin override
    owner_id = getattr(connection, "owner_user_id", None)
    if owner_id is not None and str(owner_id) == str(current_user.id):
        return connection  # the creator may manage their own connector
    raise HTTPException(
        status_code=403,
        detail="You can only manage connections you own; ask an admin for org connectors.",
    )


async def guard_owned_connection(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """FastAPI dependency: OWNER-OR-ADMIN authz on a connection mutate route.

    Wraps `_guard_private_owner` and wires the check into the route SIGNATURE so a
    new mutate route can't silently ship without authz — add
    `_guarded = Depends(guard_owned_connection)` (or `connection = Depends(...)`
    to also receive the loaded row) and the guard runs before the body. Raises
    403 for a non-owner non-admin; returns the loaded Connection otherwise.
    """
    return await _guard_private_owner(db, connection_id, organization, current_user)


# ==================== Routes ====================

@router.get("", response_model=List[ConnectionSchema])
async def list_connections(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """List connections the user has access to.

    Admins (manage_connections or full_admin_access) see all connections.
    Members see connections they have an explicit resource grant on, or
    connections backing a data source they can access (public DSes or DSes
    with an explicit grant).
    """
    connections = await connection_service.get_connections(db, organization)

    # Per-agent PRIVATE connectors (HYBRID_AGENT_CONNECTORS): a connection with
    # owner_user_id set is creator-only — exclude everyone else's private ones
    # BEFORE the permission filter, so even an admin never lists another user's
    # private connector. Org connectors (NULL owner) are untouched. No-op when
    # there are no owned connectors (e.g. flag never enabled).
    from app.services import private_connector_guard as _pcg
    connections = _pcg.filter_visible(connections, current_user)

    # Filter by user access unless admin
    resolved = await resolve_permissions(db, str(current_user.id), str(organization.id))
    is_admin = FULL_ADMIN in resolved.org_permissions or resolved.has_org_permission("manage_connections")

    if not is_admin:
        granted_conn_ids = {
            rid for (rtype, rid) in resolved.resource_permissions
            if rtype == "connection"
        }
        granted_ds_ids = {
            rid for (rtype, rid) in resolved.resource_permissions
            if rtype == "data_source"
        }
        # Public DSes in this org are visible to every member.
        public_ds_rows = await db.execute(
            select(DataSource.id).where(
                DataSource.organization_id == str(organization.id),
                DataSource.is_public.is_(True),
            )
        )
        accessible_ds_ids = granted_ds_ids | {str(r) for (r,) in public_ds_rows.all()}

        def _is_mine(c):
            oid = getattr(c, "owner_user_id", None)
            return oid is not None and str(oid) == str(current_user.id)

        def _conn_visible(c):
            # Visibility-aware list filter (non-admins). The creator always sees
            # their own connector at ANY level (even with no grant / no linked
            # data source yet).
            if _is_mine(c):
                return True
            vis = getattr(c, "visibility", None)
            if vis == "org":
                return True
            if vis == "private":
                # Not mine → invisible (filter_visible already dropped it).
                return False
            if vis == "shared":
                if str(c.id) in granted_conn_ids:
                    return True
                if c.data_sources:
                    return any(str(ds.id) in accessible_ds_ids for ds in c.data_sources)
                return False
            # Fallback when visibility is absent (legacy row): old behavior.
            if _pcg.is_private(c) and _pcg.owns(c, current_user):
                return True
            if str(c.id) in granted_conn_ids:
                return True
            if c.data_sources:
                return any(str(ds.id) in accessible_ds_ids for ds in c.data_sources)
            return False

        connections = [c for c in connections if _conn_visible(c)]

    result = []
    for conn in connections:
        # Count tables from ConnectionTable (all available tables in the database)
        count_result = await db.execute(
            select(func.count(ConnectionTable.id))
            .where(ConnectionTable.connection_id == str(conn.id))
        )
        table_count = count_result.scalar() or 0

        # Fallback for legacy connections: if ConnectionTable is empty,
        # count from DataSourceTable (existing domains using this connection)
        if table_count == 0 and conn.data_sources:
            ds_ids = [str(ds.id) for ds in conn.data_sources]
            if ds_ids:
                fallback_result = await db.execute(
                    select(func.count(DataSourceTable.id))
                    .where(DataSourceTable.datasource_id.in_(ds_ids))
                )
                table_count = fallback_result.scalar() or 0

        # Inline latest indexing for the dot status / polling.
        indexing_row = await indexing_service.get_latest(db, str(conn.id))
        indexing_payload = _indexing_to_progress(indexing_row)

        from app.schemas.data_source_registry import tool_provider_types; _TOOL_PROVIDER_TYPES = tool_provider_types()
        if conn.type in _TOOL_PROVIDER_TYPES:
            tool_count_result = await db.execute(
                select(func.count(ConnectionTool.id))
                .where(ConnectionTool.connection_id == str(conn.id))
            )
            tool_count = tool_count_result.scalar() or 0
        else:
            tool_count = 0

        # Per-user auth status (so the UI can show Connected/Disconnect vs Connect
        # for user_required connections). Cached (live_test=False) — cheap.
        user_status_payload = None
        if conn.auth_policy == "user_required":
            try:
                from app.services.user_data_source_credentials_service import UserDataSourceCredentialsService
                status = await UserDataSourceCredentialsService().build_user_status_for_connection(
                    db, conn, current_user, live_test=False
                )
                user_status_payload = status.model_dump() if hasattr(status, "model_dump") else (
                    status.dict() if hasattr(status, "dict") else status
                )
            except Exception:
                user_status_payload = None

        # User-scoped table count: for a user_required connection the UI should
        # show what THIS user can actually see (their per-user overlay), not the
        # org catalog. Mirrors the per-connection count in
        # DataSourceService._build_connections_list.
        #   'user' → count the user's accessible overlay tables
        #   'none' → 0 (no proven access)
        #   else   → keep the canonical catalog count above
        if conn.auth_policy == "user_required" and current_user and user_status_payload:
            eff_auth = user_status_payload.get("effective_auth") if isinstance(user_status_payload, dict) else None
            if eff_auth == "none":
                table_count = 0
            elif eff_auth == "user":
                from app.models.user_data_source_overlay import UserDataSourceTable
                ds_ids = [str(ds.id) for ds in (conn.data_sources or [])]
                if ds_ids:
                    user_count_result = await db.execute(
                        select(func.count(func.distinct(UserDataSourceTable.table_name)))
                        .where(
                            UserDataSourceTable.data_source_id.in_(ds_ids),
                            UserDataSourceTable.user_id == str(current_user.id),
                            UserDataSourceTable.is_accessible == True,
                        )
                    )
                    table_count = user_count_result.scalar() or 0
                else:
                    table_count = 0

        result.append(ConnectionSchema(
            id=str(conn.id),
            name=conn.name,
            type=conn.type,
            is_active=conn.is_active,
            auth_policy=conn.auth_policy,
            allowed_user_auth_modes=conn.allowed_user_auth_modes,
            last_synced_at=conn.last_synced_at.isoformat() if conn.last_synced_at else None,
            organization_id=str(conn.organization_id),
            owner_user_id=str(conn.owner_user_id) if conn.owner_user_id else None,
            visibility=getattr(conn, "visibility", None),
            table_count=0 if conn.type in _TOOL_PROVIDER_TYPES else table_count,
            tool_count=tool_count,
            agent_count=len(conn.data_sources) if conn.data_sources else 0,
            agent_names=[ds.name for ds in conn.data_sources] if conn.data_sources else [],
            indexing=indexing_payload.model_dump() if indexing_payload else None,
            user_status=user_status_payload,
        ))
    return result


@router.post("", response_model=ConnectionSchema)
async def create_connection(
    data: ConnectionCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Create a new database connection.

    3-level VISIBILITY (self-service — ANY org member may create at ANY level):
      - "private" → owner only.
      - "shared"  → owner + specifically-granted users/groups (resource_grants).
      - "org"     → all org members.
    owner_user_id is ALWAYS the creator (creator keeps edit rights) regardless of
    level. Non-private create requires HYBRID_AGENT_CONNECTORS (admins bypass, so
    legacy admin org-wide create keeps working).

    Back-compat: callers that send only the legacy `scope` ('shared'|'personal')
    are mapped via the derive rule ('shared'->'org', else 'private').
    """
    from app.settings.hybrid_flags import flags

    scope = (getattr(data, "scope", None) or "shared").lower()
    visibility = (getattr(data, "visibility", None) or "").lower()
    if visibility not in VALID_VISIBILITIES:
        # Derive from the legacy scope: 'shared' = org-wide, anything else private.
        visibility = "org" if scope == "shared" else "private"

    resolved = await resolve_permissions(db, str(current_user.id), str(organization.id))
    is_admin = (
        FULL_ADMIN in resolved.org_permissions
        or resolved.has_org_permission("manage_connections")
    )

    # Org membership is required for any self-service create.
    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == current_user.id,
                Membership.organization_id == organization.id,
            )
        )
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this organization.")

    # Non-private (shared/org) self-service create is gated by the feature flag;
    # admins always may (keeps legacy admin org-wide create working flag-off).
    if visibility != "private" and not is_admin and not flags.AGENT_CONNECTORS:
        raise HTTPException(
            status_code=403,
            detail="Shared / org-wide connectors are not enabled for this organization.",
        )

    # owner_user_id is ALWAYS the creator now (even org/shared) so the creator
    # keeps edit rights. No spoofing — taken from the session user.
    owner_user_id = str(current_user.id)

    connection = await connection_service.create_connection(
        db=db,
        organization=organization,
        current_user=current_user,
        name=data.name,
        type=data.type,
        config=data.config,
        credentials=data.credentials,
        auth_policy=data.auth_policy,
        allowed_user_auth_modes=data.allowed_user_auth_modes,
        owner_user_id=owner_user_id,
    )

    # Stamp the visibility level on the freshly-created row (the service signature
    # is left untouched — minimal core edit, mirrors the studio_id binding below).
    connection.visibility = visibility
    await db.commit()
    await db.refresh(connection)

    # Optional agent binding: a private connector created from a studio's
    # Connectors page binds to that studio so it appears in the agent's
    # "My Connectors" tab. Only meaningful for 'private'. Validate org ownership.
    studio_id = (getattr(data, "studio_id", None) or "").strip() or None
    if studio_id and visibility == "private":
        from app.models.studio import Studio
        studio = (
            await db.execute(
                select(Studio).where(
                    Studio.id == studio_id,
                    Studio.organization_id == organization.id,
                )
            )
        ).scalar_one_or_none()
        if not studio:
            raise HTTPException(status_code=404, detail="Studio not found in this organization.")
        connection.studio_id = studio_id
        await db.commit()
        await db.refresh(connection)

    # Inline the latest indexing run so the modal can show progress
    # immediately without a second roundtrip.
    from app.schemas.data_source_registry import tool_provider_types; _TOOL_PROVIDER_TYPES = tool_provider_types()
    indexing_row = await indexing_service.get_latest(db, str(connection.id))
    indexing_payload = _indexing_to_progress(indexing_row)
    return ConnectionSchema(
        id=str(connection.id),
        name=connection.name,
        type=connection.type,
        is_active=connection.is_active,
        auth_policy=connection.auth_policy,
        last_synced_at=connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        organization_id=str(connection.organization_id),
        owner_user_id=str(connection.owner_user_id) if connection.owner_user_id else None,
        visibility=getattr(connection, "visibility", None),
        table_count=0 if connection.type in _TOOL_PROVIDER_TYPES else (len(connection.connection_tables) if connection.connection_tables else 0),
        tool_count=len(connection.connection_tools) if connection.type in _TOOL_PROVIDER_TYPES and connection.connection_tools else 0,
        agent_count=len(connection.data_sources) if connection.data_sources else 0,
        indexing=indexing_payload.model_dump() if indexing_payload else None,
    )


@router.get("/{connection_id}", response_model=ConnectionDetailSchema)
async def get_connection(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Get connection details.

    The OWNER (creator) and any admin get the full editable detail (config +
    has_credentials flag) so they can edit. Other members get a redacted view
    (no config/credentials) and must have access to at least one linked data
    source; they may never view someone else's PRIVATE connector.
    """
    connection = await connection_service.get_connection(db, connection_id, organization)

    is_admin = await _is_org_admin(db, current_user, organization)
    owner_id = getattr(connection, "owner_user_id", None)
    is_owner = owner_id is not None and str(owner_id) == str(current_user.id)
    can_see_full = is_admin or is_owner

    # Non-owner non-admin: block others' private connectors + require DS access.
    from app.services import private_connector_guard as _pcg
    if not can_see_full:
        _pcg.require_owner(connection, current_user)  # 403 on someone else's private
        if not await _user_can_access_connection(db, current_user, connection):
            raise HTTPException(status_code=403, detail="Access denied to this connection")

    # Parse config if it's a string
    import json
    config = connection.config
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except:
            config = {}

    # Strip sensitive fields unless the caller owns it or is an admin.
    if not can_see_full:
        config = {}
        allowed_user_auth_modes = []
        has_credentials = False
    else:
        allowed_user_auth_modes = connection.allowed_user_auth_modes
        has_credentials = bool(connection.credentials)

    from app.schemas.data_source_registry import tool_provider_types; _TOOL_PROVIDER_TYPES = tool_provider_types()
    return ConnectionDetailSchema(
        id=str(connection.id),
        name=connection.name,
        type=connection.type,
        is_active=connection.is_active,
        auth_policy=connection.auth_policy,
        allowed_user_auth_modes=allowed_user_auth_modes,
        config=config or {},
        last_synced_at=connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        organization_id=str(connection.organization_id),
        owner_user_id=str(connection.owner_user_id) if connection.owner_user_id else None,
        table_count=0 if connection.type in _TOOL_PROVIDER_TYPES else (len(connection.connection_tables) if connection.connection_tables else 0),
        tool_count=len(connection.connection_tools) if connection.type in _TOOL_PROVIDER_TYPES and connection.connection_tools else 0,
        agent_count=len(connection.data_sources) if connection.data_sources else 0,
        agent_names=[ds.name for ds in connection.data_sources] if connection.data_sources else [],
        has_credentials=has_credentials,
        auto_reindex_enabled=bool(connection.auto_reindex_enabled),
        reindex_interval_hours=connection.reindex_interval_hours,
        next_retry_at=connection.next_retry_at.isoformat() if connection.next_retry_at else None,
        last_reindex_error=connection.last_reindex_error,
    )


@router.put("/{connection_id}", response_model=ConnectionSchema)
async def update_connection(
    connection_id: str,
    data: ConnectionUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    _guarded=Depends(guard_owned_connection),
):
    """Update a connection."""
    updates = data.dict(exclude_unset=True)
    connection = await connection_service.update_connection(
        db=db,
        connection_id=connection_id,
        organization=organization,
        current_user=current_user,
        **updates,
    )
    
    from app.schemas.data_source_registry import tool_provider_types; _TOOL_PROVIDER_TYPES = tool_provider_types()
    return ConnectionSchema(
        id=str(connection.id),
        name=connection.name,
        type=connection.type,
        is_active=connection.is_active,
        auth_policy=connection.auth_policy,
        last_synced_at=connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        organization_id=str(connection.organization_id),
        owner_user_id=str(connection.owner_user_id) if connection.owner_user_id else None,
        visibility=getattr(connection, "visibility", None),
        table_count=0 if connection.type in _TOOL_PROVIDER_TYPES else (len(connection.connection_tables) if connection.connection_tables else 0),
        tool_count=len(connection.connection_tools) if connection.type in _TOOL_PROVIDER_TYPES and connection.connection_tools else 0,
        agent_count=len(connection.data_sources) if connection.data_sources else 0,
    )


class VisibilityGrant(BaseModel):
    """A principal to grant 'shared'-visibility access to."""
    principal_type: str  # "user" | "group"
    principal_id: str


class VisibilityUpdate(BaseModel):
    """Body for PATCH /connections/{id}/visibility.

    `visibility` is one of 'private' | 'shared' | 'org'. `grants` is honored only
    when visibility=='shared' — each becomes a connection resource_grant so that
    principal can see/reuse the connector.
    """
    visibility: str
    grants: List[VisibilityGrant] = []


@router.patch("/{connection_id}/visibility", response_model=ConnectionSchema)
async def set_connection_visibility(
    connection_id: str,
    data: VisibilityUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Change a connector's 3-level visibility (owner OR admin).

    - 'private' = owner only. Clears any existing connection grants.
    - 'shared'  = owner + specifically-granted users/groups (writes resource_grants
                  for each item in `grants`; existing grants are kept).
    - 'org'     = all org members. Clears any existing connection grants.

    owner_user_id is unchanged (creator keeps edit rights). Never returns
    credentials. The data query path is untouched — visibility is management-only.
    """
    new_vis = (data.visibility or "").lower()
    if new_vis not in VALID_VISIBILITIES:
        raise HTTPException(
            status_code=400,
            detail="visibility must be one of 'private', 'shared', 'org'.",
        )

    connection = await connection_service.get_connection(db, connection_id, organization)

    # Auth: owner OR org admin (full_admin / manage_connections). No one else.
    from app.services import private_connector_guard as _pcg
    is_owner = (
        getattr(connection, "owner_user_id", None) is not None
        and str(connection.owner_user_id) == str(current_user.id)
    )
    is_admin = await _is_org_admin(db, current_user, organization)
    if not (is_owner or is_admin):
        raise HTTPException(
            status_code=403,
            detail="Only the connector's creator or an admin can change its visibility.",
        )

    old_vis = getattr(connection, "visibility", None)
    connection.visibility = new_vis

    # Manage the connection's resource_grants to match the new level.
    from app.models.resource_grant import ResourceGrant
    from app.schemas.rbac_schema import ResourceGrantCreate
    from app.services.rbac_service import rbac_service

    if new_vis == "shared":
        for g in (data.grants or []):
            ptype = (g.principal_type or "").lower()
            pid = (g.principal_id or "").strip()
            if ptype not in ("user", "group") or not pid:
                continue
            try:
                await rbac_service.create_resource_grant(
                    db,
                    str(organization.id),
                    ResourceGrantCreate(
                        resource_type="connection",
                        resource_id=str(connection.id),
                        principal_type=ptype,
                        principal_id=pid,
                        permissions=["view_schema", "query"],
                    ),
                )
            except HTTPException as e:
                # Duplicate grant (409) is fine — the principal already has access.
                if e.status_code != 409:
                    raise
    else:
        # Demote (private/org): drop any lingering connection grants so they
        # don't leak access after the level changes.
        existing = await db.execute(
            select(ResourceGrant).where(
                ResourceGrant.organization_id == str(organization.id),
                ResourceGrant.resource_type == "connection",
                ResourceGrant.resource_id == str(connection.id),
            )
        )
        for grant in existing.scalars().all():
            await db.delete(grant)

    await db.commit()
    await db.refresh(connection)

    logger.info(
        "connection.visibility_changed connection_id=%s %s->%s user_id=%s",
        str(connection.id), old_vis, new_vis, str(current_user.id),
    )

    from app.schemas.data_source_registry import tool_provider_types; _TOOL_PROVIDER_TYPES = tool_provider_types()
    indexing_row = await indexing_service.get_latest(db, str(connection.id))
    indexing_payload = _indexing_to_progress(indexing_row)
    return ConnectionSchema(
        id=str(connection.id),
        name=connection.name,
        type=connection.type,
        is_active=connection.is_active,
        auth_policy=connection.auth_policy,
        allowed_user_auth_modes=connection.allowed_user_auth_modes,
        last_synced_at=connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        organization_id=str(connection.organization_id),
        owner_user_id=str(connection.owner_user_id) if connection.owner_user_id else None,
        visibility=getattr(connection, "visibility", None),
        table_count=0 if connection.type in _TOOL_PROVIDER_TYPES else (len(connection.connection_tables) if connection.connection_tables else 0),
        tool_count=len(connection.connection_tools) if connection.type in _TOOL_PROVIDER_TYPES and connection.connection_tools else 0,
        agent_count=len(connection.data_sources) if connection.data_sources else 0,
        indexing=indexing_payload.model_dump() if indexing_payload else None,
    )


@router.delete("/{connection_id}")
async def delete_connection(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    _guarded=Depends(guard_owned_connection),
):
    """Delete a connection. Fails if connection is linked to any agents."""
    return await connection_service.delete_connection(
        db=db,
        connection_id=connection_id,
        organization=organization,
        current_user=current_user,
    )


@router.post("/test-params")
@requires_permission('manage_connections')
async def test_connection_params(
    data: ConnectionCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Test connection parameters before saving. Works for all types including MCP/API."""
    result = await connection_service.test_connection_params(
        data_source_type=data.type,
        config=data.config,
        credentials=data.credentials,
    )
    return result


@router.post("/{connection_id}/test", response_model=ConnectionTestResult)
async def test_connection(
    connection_id: str,
    overrides: ConnectionTestOverride = None,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    _guarded=Depends(guard_owned_connection),
):
    """Test a connection, optionally with override credentials/config."""
    result = await connection_service.test_connection(
        db=db,
        connection_id=connection_id,
        organization=organization,
        current_user=current_user,
        config_overrides=overrides.config if overrides else None,
        credential_overrides=overrides.credentials if overrides else None,
    )
    
    return ConnectionTestResult(
        success=result.get("success", False),
        message=result.get("message", ""),
        connectivity=result.get("connectivity", result.get("success", False)),
        schema_access=result.get("schema_access", False),
        table_count=result.get("table_count", 0),
        timings=result.get("timings"),
        details=result.get("details"),
    )


@router.post("/{connection_id}/test-my-credentials", response_model=ConnectionTestResult)
async def test_my_connection_credentials(
    connection_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Test a connection using the current user's saved credentials."""
    connection = await connection_service.get_connection(db, connection_id, organization)
    await _ensure_can_read_connection(db, organization, user, connection)
    result = await connection_service.test_user_connection(
        db=db,
        connection_id=connection_id,
        organization=organization,
        current_user=user,
    )
    return ConnectionTestResult(
        success=result.get("success", False),
        message=result.get("message", ""),
        connectivity=result.get("connectivity", result.get("success", False)),
        schema_access=result.get("schema_access", False),
        table_count=result.get("table_count", 0),
        timings=result.get("timings"),
        details=result.get("details"),
    )


@router.delete("/{connection_id}/my-credentials")
async def delete_my_connection_credentials(
    connection_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Disconnect: delete the current user's saved credentials for this connection."""
    connection = await connection_service.get_connection(db, connection_id, organization)
    await _ensure_can_read_connection(db, organization, user, connection)
    return await connection_service.delete_user_credentials(
        db=db,
        connection_id=connection_id,
        organization=organization,
        current_user=user,
    )


class QueryIdentityUpdate(BaseModel):
    query_identity: str  # "self" | "service_account"


@router.patch("/{connection_id}/query-identity")
async def set_connection_query_identity(
    connection_id: str,
    data: QueryIdentityUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    connection=Depends(guard_owned_connection),
):
    """Set the admin/owner query-identity for a delegated connection: run queries as
    the service account or as the user themselves. Persisted per (user, connection).
    """
    from app.services.connection_identity import (
        VALID_IDENTITIES,
        QUERY_IDENTITY_SERVICE,
        SERVICE_ACCOUNT_MARKER_MODE,
        supports_user_token,
        is_admin_or_owner,
        get_user_conn_cred_row,
    )
    from app.models.user_connection_credentials import UserConnectionCredentials
    from app.services.user_data_source_credentials_service import UserDataSourceCredentialsService

    identity = (data.query_identity or "").strip()
    if identity not in VALID_IDENTITIES:
        raise HTTPException(status_code=400, detail="query_identity must be 'self' or 'service_account'")

    if (connection.auth_policy or "system_only") != "user_required" or not supports_user_token(connection):
        raise HTTPException(status_code=400, detail="This connection does not support query-identity selection")
    if not await is_admin_or_owner(db, connection, current_user):
        raise HTTPException(status_code=403, detail="Only admins or owners can switch query identity")

    row = await get_user_conn_cred_row(db, connection, current_user)
    if row is None:
        # "self" is the default and needs no row. Only persist when choosing the
        # service account before ever connecting — a lightweight marker row.
        if identity == QUERY_IDENTITY_SERVICE:
            row = UserConnectionCredentials(
                connection_id=str(connection.id),
                user_id=str(current_user.id),
                organization_id=str(connection.organization_id),
                auth_mode=SERVICE_ACCOUNT_MARKER_MODE,
                is_active=True,
                is_primary=True,
                metadata_json={"query_identity": QUERY_IDENTITY_SERVICE},
            )
            row.encrypt_credentials({})
            db.add(row)
            await db.commit()
    else:
        md = dict(row.metadata_json) if isinstance(row.metadata_json, dict) else {}
        md["query_identity"] = identity
        row.metadata_json = md
        db.add(row)
        await db.commit()

    status = await UserDataSourceCredentialsService().build_user_status_for_connection(
        db, connection, current_user, live_test=False
    )
    return status.model_dump() if hasattr(status, "model_dump") else (
        status.dict() if hasattr(status, "dict") else status
    )


@router.post("/{connection_id}/refresh")
@requires_permission('manage_connections')  # Admin-only
async def refresh_connection_schema(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    connection=Depends(guard_owned_connection),
):
    """Kick off a background indexing job to refresh the connection's schema.

    Returns immediately with the indexing row. Poll `GET /connections/{id}/indexing`
    to observe progress. Idempotent — re-firing while a job is running returns
    the in-flight row.
    """
    row = await indexing_service.start(db=db, connection=connection)
    progress = _indexing_to_progress(row)
    return {
        "message": "Schema indexing started." if row.status == "pending" else "Schema indexing in progress.",
        "indexing": progress.model_dump() if progress else None,
    }


@router.post("/{connection_id}/reindex")
@requires_permission('manage_connections')
async def reindex_connection(
    connection_id: str,
    force: bool = False,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    connection=Depends(guard_owned_connection),
):
    """Kick off a background indexing job.

    Idempotent by default — returns the in-flight row if one exists.
    Pass `?force=true` to cancel any stuck row and start fresh.
    """
    from datetime import datetime
    if force:
        existing = await indexing_service.get_active(db, connection_id)
        if existing is not None:
            existing.status = "cancelled"
            existing.finished_at = datetime.utcnow()
            existing.error = "Cancelled by user reindex request"
            await db.commit()
    row = await indexing_service.start(db=db, connection=connection)
    progress = _indexing_to_progress(row)
    return {
        "message": "Schema indexing started." if row.status == "pending" else "Schema indexing in progress.",
        "indexing": progress.model_dump() if progress else None,
    }


@router.post("/{connection_id}/my-schema/refresh")
async def refresh_my_connection_schema(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Re-fetch the CURRENT user's accessible schema for a user_required
    connection (their per-user overlay), using their own credentials.

    This is the per-user counterpart to /reindex — which re-indexes the shared
    catalog via the service principal and is admin-only. Here each user refreshes
    only what they can see, so a Fabric/OBO user can pull in tables they gained
    access to without an admin reindex.
    """
    import logging
    logger = logging.getLogger(__name__)
    connection = await connection_service.get_connection(db, connection_id, organization)
    await _ensure_can_read_connection(db, organization, current_user, connection)

    from app.services.data_source_service import DataSourceService
    from app.models.user_data_source_overlay import UserDataSourceTable
    ds_service = DataSourceService()
    for ds in (connection.data_sources or []):
        try:
            # Live fetch with the user's creds + upsert their overlay (same path
            # the OAuth callback runs after sign-in).
            await ds_service.get_user_data_source_schema(db=db, data_source=ds, user=current_user)
        except Exception as e:
            logger.warning(f"Per-user schema refresh failed for data source {ds.id}: {e}")

    # Recompute the user's accessible table count for this connection.
    ds_ids = [str(ds.id) for ds in (connection.data_sources or [])]
    table_count = 0
    if ds_ids:
        result = await db.execute(
            select(func.count(func.distinct(UserDataSourceTable.table_name)))
            .where(
                UserDataSourceTable.data_source_id.in_(ds_ids),
                UserDataSourceTable.user_id == str(current_user.id),
                UserDataSourceTable.is_accessible == True,
            )
        )
        table_count = result.scalar() or 0
    return {"message": "Schema refreshed", "table_count": table_count}


@router.get("/{connection_id}/indexing", response_model=ConnectionIndexingProgress)
async def get_connection_indexing(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Return the latest indexing row for this connection. 404 if none exists."""
    connection = await connection_service.get_connection(db, connection_id, organization)
    await _ensure_can_read_connection(db, organization, current_user, connection)
    row = await indexing_service.get_latest(db, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No indexing runs found for this connection")
    return _indexing_to_progress(row)


async def _ensure_can_read_connection(db, organization, current_user, connection):
    """Allow read if user is admin, has an explicit connection grant, or the
    connection backs a data source the user can access (public DS or DS grant).
    Raises 403 otherwise.
    """
    # CREATOR-ONLY: a private connector is creator-only — owner passes, anyone
    # else (incl. admins) is 403'd here BEFORE the org-permission fallthrough.
    # No-op for org connectors.
    from app.services import private_connector_guard as _pcg
    if _pcg.is_private(connection):
        _pcg.require_owner(connection, current_user)
        return

    resolved = await resolve_permissions(db, str(current_user.id), str(organization.id))
    if FULL_ADMIN in resolved.org_permissions or resolved.has_org_permission("manage_connections"):
        return
    if resolved.has_resource_permission("connection", str(connection.id), "view"):
        return
    granted_ds_ids = {
        rid for (rtype, rid) in resolved.resource_permissions if rtype == "data_source"
    }
    public_rows = await db.execute(
        select(DataSource.id).where(
            DataSource.organization_id == str(organization.id),
            DataSource.is_public.is_(True),
        )
    )
    accessible_ds_ids = granted_ds_ids | {str(r) for (r,) in public_rows.all()}
    if connection.data_sources and any(str(ds.id) in accessible_ds_ids for ds in connection.data_sources):
        return
    raise HTTPException(status_code=403, detail="Access denied to this connection")


@router.get("/{connection_id}/tables", response_model=List[ConnectionTableSchema])
async def get_connection_tables(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Get tables for a connection."""
    connection = await connection_service.get_connection(db, connection_id, organization)
    await _ensure_can_read_connection(db, organization, current_user, connection)

    result = []
    for table in (connection.connection_tables or []):
        result.append(ConnectionTableSchema(
            id=str(table.id),
            name=table.name,
            column_count=len(table.columns) if table.columns else 0,
        ))
    return result


# ==================== Tool Management Routes (MCP / Custom API) ====================

@router.post("/{connection_id}/refresh-tools", response_model=List[ConnectionToolSchema])
@requires_permission('manage_connections')
async def refresh_connection_tools(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    connection=Depends(guard_owned_connection),
):
    """Refresh/discover tools for an MCP or Custom API connection."""
    tools = await connection_service.refresh_tools(db, connection, current_user)
    return [
        ConnectionToolSchema(
            id=str(t.id),
            name=t.name,
            description=t.description,
            is_enabled=t.is_enabled,
            policy=t.policy,
            connection_id=str(t.connection_id),
            input_schema=t.input_schema,
            output_schema=t.output_schema,
        )
        for t in tools
    ]


@router.get("/{connection_id}/tools", response_model=List[ConnectionToolSchema])
async def get_connection_tools_list(
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Get all tools for a connection."""
    connection = await connection_service.get_connection(db, connection_id, organization)
    await _ensure_can_read_connection(db, organization, current_user, connection)
    tools = await connection_service.get_connection_tools(db, connection_id)
    return [
        ConnectionToolSchema(
            id=str(t.id),
            name=t.name,
            description=t.description,
            is_enabled=t.is_enabled,
            policy=t.policy,
            connection_id=str(t.connection_id),
            input_schema=t.input_schema,
            output_schema=t.output_schema,
        )
        for t in tools
    ]


@router.put("/{connection_id}/tools/batch", response_model=List[ConnectionToolSchema])
@requires_permission('manage_connections')
async def batch_update_connection_tools(
    connection_id: str,
    data: BatchToolUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    _guarded=Depends(guard_owned_connection),
):
    """Batch enable/disable tools."""
    tools = await connection_service.batch_update_tools(db, data.tool_ids, data.is_enabled)
    return [
        ConnectionToolSchema(
            id=str(t.id),
            name=t.name,
            description=t.description,
            is_enabled=t.is_enabled,
            policy=t.policy,
            connection_id=str(t.connection_id),
            input_schema=t.input_schema,
            output_schema=t.output_schema,
        )
        for t in tools
    ]


@router.put("/{connection_id}/tools/{tool_id}", response_model=ConnectionToolSchema)
@requires_permission('manage_connections')
async def update_tool(
    connection_id: str,
    tool_id: str,
    data: ConnectionToolUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    _guarded=Depends(guard_owned_connection),
):
    """Enable/disable a tool or update its policy."""
    tool = await connection_service.update_connection_tool(
        db, tool_id, is_enabled=data.is_enabled, policy=data.policy
    )
    return ConnectionToolSchema(
        id=str(tool.id),
        name=tool.name,
        description=tool.description,
        is_enabled=tool.is_enabled,
        policy=tool.policy,
        connection_id=str(tool.connection_id),
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
    )

