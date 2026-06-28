"""Studio data-source pinning API (hybrid Studios ST2).

Pin existing Data Agents (DataSource rows) as the *sources* of a Studio. A
Studio chat is grounded only on the DataSources pinned here (retrieval scoping
lives in the schema context builder + report-create auto-population).

Additive: this NEVER mutates the `data_sources` table — it only references it
via the `studio_data_sources` join (StudioDataSource: studio_id, agent_id where
agent_id -> data_sources.id). All behavior is gated by flags.STUDIOS and every
route resolves the caller's effective Studio role first.

This router is mounted under /api by main.py (registered as
`studio_sources.router`).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import current_user
from app.core.permission_resolver import resolve_permissions, FULL_ADMIN
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.connection import Connection
from app.models.data_source import DataSource
from app.models.organization import Organization
from app.models.studio import StudioDataSource
from app.models.user import User
from app.schemas.connection_schema import ConnectionCreate, ConnectionUpdate
from app.services.connection_service import ConnectionService
from app.services.studio_access import resolve_studio_access
from app.services import private_connector_guard as pcg
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may mutate a Studio's pinned sources (add/remove).
_EDITOR_ROLES = {"owner", "editor"}


class StudioSourcePin(BaseModel):
    """Request body to pin a Data Agent as a Studio source."""
    agent_id: str


class StudioSourceRead(BaseModel):
    """A pinned Data Agent source on a Studio (echoes the DataSource summary)."""
    id: str                      # StudioDataSource row id
    studio_id: str
    agent_id: str                # data_sources.id
    name: Optional[str] = None   # resolved DataSource name (echo-only)
    type: Optional[str] = None   # resolved DataSource type (echo-only)

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


@router.get("/studios/{studio_id}/sources", response_model=List[StudioSourceRead])
async def list_studio_sources(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List the Data Agents pinned as sources for a Studio (viewer+)."""
    _require_flag()
    await _require_role(db, studio_id, current_user)

    res = await db.execute(
        select(StudioDataSource)
        .where(
            StudioDataSource.studio_id == studio_id,
            StudioDataSource.deleted_at.is_(None),
        )
        .order_by(StudioDataSource.created_at.asc())
    )
    pins = list(res.scalars().all())
    if not pins:
        return []

    # Resolve DataSource display fields (org-scoped) in a single query.
    agent_ids = [p.agent_id for p in pins]
    ds_res = await db.execute(
        select(DataSource).where(
            DataSource.id.in_(agent_ids),
            DataSource.organization_id == organization.id,
        )
    )
    ds_by_id = {str(d.id): d for d in ds_res.scalars().all()}

    out: List[StudioSourceRead] = []
    for p in pins:
        ds = ds_by_id.get(str(p.agent_id))
        out.append(
            StudioSourceRead(
                id=str(p.id),
                studio_id=str(p.studio_id),
                agent_id=str(p.agent_id),
                name=getattr(ds, "name", None) if ds is not None else None,
                type=getattr(ds, "type", None) if ds is not None else None,
            )
        )
    return out


@router.post("/studios/{studio_id}/sources", response_model=StudioSourceRead)
async def pin_studio_source(
    studio_id: str,
    body: StudioSourcePin,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Pin a Data Agent as a Studio source (editor+). Idempotent (deduped)."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    # The pinned source must be a DataSource the caller's org actually owns.
    ds_res = await db.execute(
        select(DataSource).where(
            DataSource.id == body.agent_id,
            DataSource.organization_id == organization.id,
        )
    )
    ds = ds_res.scalar_one_or_none()
    if ds is None:
        raise AppError.not_found(
            ErrorCode.DATA_SOURCE_NOT_FOUND, "Data source not found"
        )

    # Dedupe: a (studio, agent) pin is unique. Return the existing row.
    existing_res = await db.execute(
        select(StudioDataSource).where(
            StudioDataSource.studio_id == studio_id,
            StudioDataSource.agent_id == body.agent_id,
            StudioDataSource.deleted_at.is_(None),
        )
    )
    pin = existing_res.scalar_one_or_none()
    if pin is None:
        pin = StudioDataSource(studio_id=studio_id, agent_id=body.agent_id)
        db.add(pin)
        await db.commit()
        await db.refresh(pin)

    # ST7: now that a source schema is available, regenerate grounded context
    # (summary1/suggestedQs LIVE + instructions/examples PENDING) in the
    # BACKGROUND. Idempotent via bootstrap_state; flag-gated; never breaks pin.
    from app.services.studio_bootstrap import schedule_bootstrap_on_source_pin

    schedule_bootstrap_on_source_pin(background_tasks, studio_id)

    return StudioSourceRead(
        id=str(pin.id),
        studio_id=str(pin.studio_id),
        agent_id=str(pin.agent_id),
        name=getattr(ds, "name", None),
        type=getattr(ds, "type", None),
    )


@router.delete("/studios/{studio_id}/sources/{agent_id}")
async def unpin_studio_source(
    studio_id: str,
    agent_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Unpin a Data Agent from a Studio (editor+). Soft-deletes the join row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    res = await db.execute(
        select(StudioDataSource).where(
            StudioDataSource.studio_id == studio_id,
            StudioDataSource.agent_id == agent_id,
            StudioDataSource.deleted_at.is_(None),
        )
    )
    pin = res.scalar_one_or_none()
    if pin is None:
        raise AppError.not_found("studio.source_not_found", "Studio source not found")

    # Soft-delete (matches resolve_studio_access / list filtering on deleted_at).
    from datetime import datetime

    pin.deleted_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "studio_id": studio_id, "agent_id": agent_id}


# --------------------------------------------------------------------------- #
# Per-agent PRIVATE connectors (HYBRID_AGENT_CONNECTORS)
# --------------------------------------------------------------------------- #
# A studio owner/editor can create a connector that is PRIVATE to them and BOUND
# to this one studio (Connection.owner_user_id + Connection.studio_id set). It is
# auto-wrapped in a private DataSource (is_public=False, owner=creator) and pinned
# to the studio. Creator-only + non-shareable invariants live in
# private_connector_guard; this endpoint is the only way an owned connector is born.

_connection_service = ConnectionService()


class StudioConnectorRead(BaseModel):
    """Result of creating/listing a studio-private connector."""
    connection_id: str
    data_source_id: Optional[str] = None
    studio_id: str
    name: str
    type: str
    owner_user_id: str
    pinned: bool = False


class StudioConnectorListItem(BaseModel):
    """A connector row in the studio Connectors page (My / Shared tab).

    ``active`` = at least one of the connector's DataSources is currently pinned
    (StudioDataSource, not soft-deleted) to this studio — only ACTIVE connectors
    are queryable by the agent and get data sync.
    """
    connection_id: str
    name: str
    type: str
    owner_user_id: Optional[str] = None
    visibility: Optional[str] = None     # 'private' | 'shared' | 'org' (FE badge)
    is_org: bool = False                 # shared/org connector (vs my private)
    active: bool = False                 # pinned to this studio → agent can use it
    data_source_id: Optional[str] = None
    sync_status: Optional[str] = None    # Connection.last_connection_status
    last_synced_at: Optional[str] = None
    table_count: Optional[int] = None


class StudioConnectorsResponse(BaseModel):
    """Two-tab payload for the studio Connectors page."""
    mine: List[StudioConnectorListItem] = []
    shared: List[StudioConnectorListItem] = []


class ActivateResult(BaseModel):
    ok: bool = True
    connection_id: str
    data_source_id: str
    active: bool


def _require_agent_connectors() -> None:
    """404 (feature locked) unless HYBRID_AGENT_CONNECTORS is on — mirrors
    me_groups `_ensure_enabled` / `_require_flag` so the route's existence isn't
    leaked when the feature is off.
    """
    pcg.require_feature_enabled()


async def _pinned_ds_ids(db: AsyncSession, studio_id: str) -> set:
    """DataSource ids currently pinned (active) to this studio."""
    res = await db.execute(
        select(StudioDataSource.agent_id).where(
            StudioDataSource.studio_id == studio_id,
            StudioDataSource.deleted_at.is_(None),
        )
    )
    return {str(r) for (r,) in res.all()}


def _connector_item(c: Connection, *, is_org: bool, pinned: set) -> StudioConnectorListItem:
    ds_list = list(getattr(c, "data_sources", None) or [])
    active_ds = next((str(ds.id) for ds in ds_list if str(ds.id) in pinned), None)
    ds_id = active_ds or (str(ds_list[0].id) if ds_list else None)
    last = getattr(c, "last_synced_at", None)
    return StudioConnectorListItem(
        connection_id=str(c.id),
        name=c.name,
        type=c.type,
        owner_user_id=str(c.owner_user_id) if c.owner_user_id else None,
        visibility=getattr(c, "visibility", None),
        is_org=is_org,
        active=active_ds is not None,
        data_source_id=ds_id,
        sync_status=getattr(c, "last_connection_status", None),
        last_synced_at=last.isoformat() if last is not None else None,
    )


@router.get("/studios/{studio_id}/connectors", response_model=StudioConnectorsResponse)
async def list_studio_connectors(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Two-tab connector list for a studio: ``mine`` + ``shared``.

    * **mine** — connectors the caller OWNS (``owner_user_id == me``) at ANY
      visibility level (the creator keeps edit rights everywhere).
    * **shared** — connectors NOT owned by the caller that are visible to them:
      ``visibility=='org'``, or (``visibility=='shared'`` AND granted to them /
      admin), or legacy admin-made org connectors (``owner_user_id`` NULL).
      Private connectors owned by other users are NEVER listed.

    Each row carries ``active`` = whether one of its DataSources is pinned to this
    studio. Only ACTIVE connectors are queryable by the agent + get data sync.
    """
    _require_agent_connectors()
    await _require_role(db, studio_id, current_user)

    pinned = await _pinned_ds_ids(db, studio_id)

    # ── MINE: every connector owned by the caller, any visibility level ─────────
    mine_res = await db.execute(
        select(Connection)
        .options(selectinload(Connection.data_sources))
        .where(
            Connection.organization_id == organization.id,
            Connection.owner_user_id == str(current_user.id),
        )
    )
    mine = [
        _connector_item(c, is_org=False, pinned=pinned)
        for c in mine_res.scalars().all()
    ]

    # ── SHARED: org/shared connectors the caller may reuse ─────────────────────
    all_conns = await _connection_service.get_connections(db, organization)
    resolved = await resolve_permissions(db, str(current_user.id), str(organization.id))
    is_admin = (
        FULL_ADMIN in resolved.org_permissions
        or resolved.has_org_permission("manage_connections")
    )
    granted_conn_ids = {
        rid for (rtype, rid) in resolved.resource_permissions if rtype == "connection"
    }
    granted_ds_ids = {
        rid for (rtype, rid) in resolved.resource_permissions if rtype == "data_source"
    }
    public_ds_rows = await db.execute(
        select(DataSource.id).where(
            DataSource.organization_id == str(organization.id),
            DataSource.is_public.is_(True),
        )
    )
    accessible_ds_ids = granted_ds_ids | {str(r) for (r,) in public_ds_rows.all()}

    def _shared_visible(c: Connection) -> bool:
        # Owned by the caller → belongs in `mine`, not here.
        oid = getattr(c, "owner_user_id", None)
        if oid is not None and str(oid) == str(current_user.id):
            return False
        vis = getattr(c, "visibility", None)
        # Legacy admin-made org connector (owner NULL) = org-wide, everyone sees.
        if oid is None and vis in (None, "org"):
            return True
        if vis == "org":
            return True
        if vis == "private":
            # Another user's private connector never appears in Shared.
            return False
        if vis == "shared":
            if is_admin:
                return True
            if str(c.id) in granted_conn_ids:
                return True
            if c.data_sources:
                return any(str(ds.id) in accessible_ds_ids for ds in c.data_sources)
            return False
        # Fallback (no visibility attr on a legacy row): old behavior — private
        # (owner set) hidden; otherwise admin/grant/public-DS visible.
        if pcg.is_private(c):
            return False
        if is_admin:
            return True
        if str(c.id) in granted_conn_ids:
            return True
        if c.data_sources:
            return any(str(ds.id) in accessible_ds_ids for ds in c.data_sources)
        return False

    shared = [
        _connector_item(c, is_org=True, pinned=pinned)
        for c in all_conns
        if _shared_visible(c)
    ]

    return StudioConnectorsResponse(mine=mine, shared=shared)


@router.post("/studios/{studio_id}/connectors", response_model=StudioConnectorRead)
async def create_studio_connector(
    studio_id: str,
    body: ConnectionCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Create a PRIVATE connector bound to this studio (owner/editor only).

    The connector is creator-only and non-shareable. It is wrapped in a private
    DataSource and pinned to the studio so the agent can use it immediately.
    """
    _require_agent_connectors()
    await _require_role(db, studio_id, current_user, editor=True)

    # 1. Create the Connection via the existing service (validation, indexing,
    #    audit). Then stamp ownership + studio binding and persist.
    connection = await _connection_service.create_connection(
        db=db,
        organization=organization,
        current_user=current_user,
        name=body.name,
        type=body.type,
        config=body.config,
        credentials=body.credentials,
        auth_policy=body.auth_policy,
        allowed_user_auth_modes=body.allowed_user_auth_modes,
    )
    # Re-load the ORM row (create_connection returns an eager-loaded copy) and
    # mark it private + studio-bound. Stamping after creation keeps the service
    # signature untouched (minimal core edit).
    conn_row = (await db.execute(
        select(Connection).where(Connection.id == connection.id)
    )).scalar_one()
    conn_row.owner_user_id = str(current_user.id)
    conn_row.studio_id = str(studio_id)
    conn_row.visibility = "private"
    await db.commit()
    await db.refresh(conn_row)

    # 2. Auto-create a PRIVATE DataSource wrapping this connection and link it
    #    (same M:N append the data-source service uses). owner=creator,
    #    is_public=False — never shared.
    ds = DataSource(
        name=conn_row.name,
        organization_id=organization.id,
        is_public=False,
        use_llm_sync=False,
        owner_user_id=current_user.id,
    )
    ds.connections.append(conn_row)
    db.add(ds)
    try:
        await db.commit()
        await db.refresh(ds)
    except IntegrityError:
        await db.rollback()
        # Name clash with an existing data source — fall back to a unique name.
        ds = DataSource(
            name=f"{conn_row.name}-{str(conn_row.id)[:8]}",
            organization_id=organization.id,
            is_public=False,
            use_llm_sync=False,
            owner_user_id=current_user.id,
        )
        ds.connections.append(conn_row)
        db.add(ds)
        await db.commit()
        await db.refresh(ds)

    # 3. Pin the DataSource to the studio (reuse the StudioDataSource join +
    #    bootstrap hook used by pin_studio_source).
    pin = StudioDataSource(studio_id=str(studio_id), agent_id=str(ds.id))
    db.add(pin)
    await db.commit()

    from app.services.studio_bootstrap import schedule_bootstrap_on_source_pin
    schedule_bootstrap_on_source_pin(background_tasks, str(studio_id))

    return StudioConnectorRead(
        connection_id=str(conn_row.id),
        data_source_id=str(ds.id),
        studio_id=str(studio_id),
        name=conn_row.name,
        type=conn_row.type,
        owner_user_id=str(current_user.id),
        pinned=True,
    )


@router.post(
    "/studios/{studio_id}/connectors/{connection_id}/activate",
    response_model=ActivateResult,
)
async def activate_studio_connector(
    studio_id: str,
    connection_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Activate a connector for this agent (owner/editor only).

    "Active" = a DataSource wrapping the connector is pinned to this studio, so
    the agent can query it and a data sync is triggered. Works for the caller's
    own private connectors AND shared/org connectors they may reuse. A shared
    connector with no DataSource yet gets one auto-created (private to the studio
    pin; the connector itself is unchanged). Idempotent.
    """
    _require_agent_connectors()
    await _require_role(db, studio_id, current_user, editor=True)

    res = await db.execute(
        select(Connection)
        .options(selectinload(Connection.data_sources))
        .where(
            Connection.id == connection_id,
            Connection.organization_id == organization.id,
        )
    )
    conn = res.scalar_one_or_none()
    if conn is None:
        raise AppError.not_found("connection.not_found", "Connector not found")
    # A private connector owned by SOMEONE ELSE can never be activated here.
    if pcg.is_private(conn) and not pcg.owns(conn, current_user):
        raise AppError.forbidden(
            ErrorCode.ACCESS_DENIED, "This is a private connector of another user."
        )

    # Ensure a DataSource wraps the connection (reuse the first existing one).
    ds_list = list(conn.data_sources or [])
    if ds_list:
        ds = ds_list[0]
    else:
        ds = DataSource(
            name=conn.name,
            organization_id=organization.id,
            is_public=False,
            use_llm_sync=False,
            owner_user_id=current_user.id,
        )
        ds.connections.append(conn)
        db.add(ds)
        try:
            await db.commit()
            await db.refresh(ds)
        except IntegrityError:
            await db.rollback()
            ds = DataSource(
                name=f"{conn.name}-{str(conn.id)[:8]}",
                organization_id=organization.id,
                is_public=False,
                use_llm_sync=False,
                owner_user_id=current_user.id,
            )
            ds.connections.append(conn)
            db.add(ds)
            await db.commit()
            await db.refresh(ds)

    # Pin (dedupe + reactivate a previously soft-deleted pin).
    existing = await db.execute(
        select(StudioDataSource).where(
            StudioDataSource.studio_id == studio_id,
            StudioDataSource.agent_id == str(ds.id),
        )
    )
    pin = existing.scalar_one_or_none()
    if pin is None:
        db.add(StudioDataSource(studio_id=str(studio_id), agent_id=str(ds.id)))
        await db.commit()
    elif pin.deleted_at is not None:
        pin.deleted_at = None
        await db.commit()

    # Trigger data sync / grounded-context regen in the background.
    from app.services.studio_bootstrap import schedule_bootstrap_on_source_pin
    schedule_bootstrap_on_source_pin(background_tasks, str(studio_id))

    return ActivateResult(
        ok=True, connection_id=str(conn.id), data_source_id=str(ds.id), active=True
    )


@router.delete("/studios/{studio_id}/connectors/{connection_id}/activate")
async def deactivate_studio_connector(
    studio_id: str,
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Deactivate a connector for this agent (owner/editor only).

    Soft-deletes the StudioDataSource pin(s) for every DataSource wrapping this
    connector — the agent can no longer query it. The connector + its DataSource
    are left intact (re-activate any time). Idempotent.
    """
    _require_agent_connectors()
    await _require_role(db, studio_id, current_user, editor=True)

    res = await db.execute(
        select(Connection)
        .options(selectinload(Connection.data_sources))
        .where(
            Connection.id == connection_id,
            Connection.organization_id == organization.id,
        )
    )
    conn = res.scalar_one_or_none()
    if conn is None:
        raise AppError.not_found("connection.not_found", "Connector not found")

    ds_ids = [str(ds.id) for ds in (conn.data_sources or [])]
    if ds_ids:
        from datetime import datetime

        pins = await db.execute(
            select(StudioDataSource).where(
                StudioDataSource.studio_id == studio_id,
                StudioDataSource.agent_id.in_(ds_ids),
                StudioDataSource.deleted_at.is_(None),
            )
        )
        for pin in pins.scalars().all():
            pin.deleted_at = datetime.utcnow()
        await db.commit()

    return {"ok": True, "connection_id": str(conn.id), "active": False}


async def _load_studio_private_connector(
    db: AsyncSession, studio_id: str, connection_id: str, user: User, organization
) -> Connection:
    """Load a connection that is PRIVATE, owned by `user`, and BOUND to this
    studio — or raise. 404 when it isn't a private connector of this studio
    (existence not leaked); 403 when it exists but `user` isn't the owner.

    Eager-loads data_sources (+ their connections) so the DELETE teardown can
    run without a lazy load in async context.
    """
    res = await db.execute(
        select(Connection)
        .options(selectinload(Connection.data_sources).options(selectinload(DataSource.connections)))
        .where(
            Connection.id == connection_id,
            Connection.organization_id == organization.id,
            Connection.studio_id == str(studio_id),
        )
    )
    conn = res.scalar_one_or_none()
    # Must be a private connector bound to THIS studio. A NULL-owner (org) or
    # other-studio connection is "not found" here — this surface only serves
    # studio-private connectors.
    if conn is None or not pcg.is_private(conn):
        raise AppError.not_found(
            "connection.not_found", "Connector not found for this studio"
        )
    # CREATOR-ONLY: owned-but-not-by-you → 403 (no admin bypass).
    pcg.require_owner(conn, user)
    return conn


@router.put("/studios/{studio_id}/connectors/{connection_id}", response_model=StudioConnectorRead)
async def update_studio_connector(
    studio_id: str,
    connection_id: str,
    body: ConnectionUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Update a studio-private connector (owner/editor + creator-only).

    Partial update. Blank/absent credentials are DROPPED so the stored secret is
    preserved — mirrors connection.py PUT's empty-credentials handling (the
    service only re-encrypts when credentials is non-empty with no None values).
    """
    _require_agent_connectors()
    await _require_role(db, studio_id, current_user, editor=True)
    await _load_studio_private_connector(db, studio_id, connection_id, current_user, organization)

    updates = body.dict(exclude_unset=True)
    # Preserve the stored secret when the client sends no (or blank) credentials.
    # The frontend drops blank credentials before saving; treat an empty/None or
    # all-blank credentials dict as "keep existing" by not forwarding the key.
    creds = updates.get("credentials")
    if creds is None or (isinstance(creds, dict) and not any(
        (v is not None and v != "") for v in creds.values()
    )):
        updates.pop("credentials", None)

    connection = await _connection_service.update_connection(
        db=db,
        connection_id=connection_id,
        organization=organization,
        current_user=current_user,
        **updates,
    )
    return StudioConnectorRead(
        connection_id=str(connection.id),
        data_source_id=None,
        studio_id=str(studio_id),
        name=connection.name,
        type=connection.type,
        owner_user_id=str(current_user.id),
        pinned=True,
    )


@router.delete("/studios/{studio_id}/connectors/{connection_id}")
async def delete_studio_connector(
    studio_id: str,
    connection_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Delete a studio-private connector (owner/editor + creator-only).

    Hard-deletes the connection (Fernet user_credentials / tools cascade), and
    removes the wrapping private DataSource + its StudioDataSource pin. Reuses
    the same teardown as studio delete.
    """
    _require_agent_connectors()
    await _require_role(db, studio_id, current_user, editor=True)
    conn = await _load_studio_private_connector(
        db, studio_id, connection_id, current_user, organization
    )

    await pcg.teardown_private_connection(db, conn)
    await db.commit()
    return {"ok": True}
