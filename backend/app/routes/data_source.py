from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload


def _journey_v2() -> bool:
    """Connector journey v2 (flag HYBRID_CONNECTOR_JOURNEY_V2): confirm identity +
    consent + explicit sync instead of auto-sync. Fail-soft → False (legacy)."""
    try:
        from app.settings.hybrid_flags import flags as _jf
        return bool(getattr(_jf, "CONNECTOR_JOURNEY_V2", False))
    except Exception:
        return False
from app.dependencies import get_async_db, release_request_db
from typing import Optional, List, Union

from app.models.user import User
from app.core.auth import current_user
from app.models.organization import Organization
from app.dependencies import get_current_organization
from app.services.data_source_service import DataSourceService
from app.schemas.data_source_schema import DataSourceCreate, DataSourceBase, DataSourceSchema, DataSourceUpdate, DataSourceMembershipCreate, DataSourceListItemSchema
from app.schemas.metadata_indexing_job_schema import MetadataIndexingJobSchema
from app.schemas.data_source_schema import DataSourceMembershipSchema
from app.schemas.datasource_table_schema import (
    DataSourceTableSchema,
    PaginatedTablesResponse,
    BulkUpdateTablesRequest,
    DeltaUpdateTablesRequest,
    DeltaUpdateTablesResponse,
)
from app.core.permissions_decorator import requires_permission, requires_resource_permission, check_resource_permissions
from app.models.data_source import DataSource

router = APIRouter(tags=["data_sources"])

# ---------------------------------------------------------------------------
# Overview cache — the agent Overview page recomputes get_data_source_schema
# (all tables + columns) on EVERY open, which is the whole load cost. The result
# only changes on a sync, so cache it per (data_source, user) with a short TTL and
# bust it explicitly when a sync completes. Module-level (per worker); fail-open —
# any cache error just recomputes. Keyed by user because per-user connector
# overlays differ between users.
# ---------------------------------------------------------------------------
import time as _time
_OVERVIEW_CACHE: dict = {}
_OVERVIEW_TTL = 300.0
_OVERVIEW_MAX = 512


def _overview_cache_get(ds_id: str, user_id: str):
    try:
        ent = _OVERVIEW_CACHE.get((ds_id, user_id))
        if not ent:
            return None
        exp, payload = ent
        if exp < _time.monotonic():
            _OVERVIEW_CACHE.pop((ds_id, user_id), None)
            return None
        return payload
    except Exception:
        return None


def _overview_cache_put(ds_id: str, user_id: str, payload: dict) -> None:
    try:
        if len(_OVERVIEW_CACHE) >= _OVERVIEW_MAX:
            now = _time.monotonic()
            for k in [k for k, (e, _) in _OVERVIEW_CACHE.items() if e < now]:
                _OVERVIEW_CACHE.pop(k, None)
            while len(_OVERVIEW_CACHE) >= _OVERVIEW_MAX:
                _OVERVIEW_CACHE.pop(next(iter(_OVERVIEW_CACHE)), None)
        _OVERVIEW_CACHE[(ds_id, user_id)] = (_time.monotonic() + _OVERVIEW_TTL, payload)
    except Exception:
        pass


def invalidate_overview_cache(ds_id: str) -> None:
    """Drop all cached overviews for a data source (any user). Call on sync."""
    try:
        for k in [k for k in _OVERVIEW_CACHE if k[0] == str(ds_id)]:
            _OVERVIEW_CACHE.pop(k, None)
    except Exception:
        pass
data_source_service = DataSourceService()

@router.get("/available_data_sources", response_model=list[dict])
async def get_available_data_sources(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await data_source_service.get_available_data_sources(db, organization)

@router.get("/data_sources", response_model=list[DataSourceListItemSchema])
async def get_data_sources(
    show_all: bool = Query(False, description="Admin 'show all' view: include every data source in the org (private ones too). Only honored for callers with org-wide data-source governance (full_admin_access / manage_connections); ignored otherwise."),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await data_source_service.get_data_sources(db, current_user, organization, show_all=show_all)


def _tier_of(scope_kind: str) -> str:
    """Map a scope_kind to a user-facing memory TIER."""
    if scope_kind == "org":
        return "global"     # all agents
    if scope_kind == "user":
        return "personal"   # private
    return "data"           # model / schema / file — shared by data


def _serialize_knowledge(r) -> dict:
    """Shape an AgentKnowledge row for the Memory UI (never leaks raw content
    beyond the already-sanitized content_json)."""
    return {
        "id": r.id,
        "tier": _tier_of(r.scope_kind),
        "scope_kind": r.scope_kind,
        "scope_key": r.scope_key,
        "kind": r.kind,
        "title": r.title,
        "text": r.text,
        "content": r.content_json,
        "verified_count": r.verified_count,
        "status": r.status,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/data_sources/{data_source_id}/memory")
async def get_agent_memory(
    data_source_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Shared Memory this agent reuses — the reusable, sanitized facts visible
    to the current user under this agent's scopes. Empty unless HYBRID_SHARED_MEMORY."""
    from app.settings.hybrid_flags import flags
    if not flags.SHARED_MEMORY:
        return {"enabled": False, "items": []}
    from app.services.knowledge import retrieve as R
    rows = await R.recall_items(
        db, organization_id=str(organization.id),
        current_user_id=str(current_user.id), data_source_ids=[str(data_source_id)],
    )
    return {"enabled": True, "items": [_serialize_knowledge(r) for r in rows]}


@router.post("/data_sources/{data_source_id}/auto-eda")
async def rebuild_agent_eda(
    data_source_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Rebuild this agent's Auto-EDA profile on demand (BI-uplift Phase 6).
    Recomputes the profile from a fresh data sample + re-narrates, saving to
    data_sources.eda_profile. No-op unless HYBRID_AUTO_EDA."""
    from app.settings.hybrid_flags import flags
    if not flags.AUTO_EDA:
        return {"enabled": False, "eda": None}
    ds = (await db.execute(
        select(DataSource).where(
            DataSource.id == str(data_source_id),
            DataSource.organization_id == str(organization.id),
        )
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="not found")
    model = None
    try:
        from app.services.llm_service import LLMService
        model = await LLMService().get_default_model(db, organization)
    except Exception:
        model = None
    from app.services.analytics.agent_eda import build_agent_eda
    payload = await build_agent_eda(
        db, organization=organization, data_source=ds, model=model)
    return {"enabled": True, "eda": payload}


@router.post("/data_sources/{data_source_id}/kpis")
async def rebuild_agent_kpis(
    data_source_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Rebuild this agent's governed KPI set on demand (BI-uplift Phase 3).
    Proposes outcome-first, leading/lagging-tagged KPIs from the agent's data
    profile, saving to data_sources.kpi_defs. No-op unless HYBRID_KPI_LAYER."""
    from app.settings.hybrid_flags import flags
    if not flags.KPI_LAYER:
        return {"enabled": False, "kpis": None}
    ds = (await db.execute(
        select(DataSource).where(
            DataSource.id == str(data_source_id),
            DataSource.organization_id == str(organization.id),
        )
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="not found")
    model = None
    try:
        from app.services.llm_service import LLMService
        model = await LLMService().get_default_model(db, organization)
    except Exception:
        model = None
    from app.services.analytics.agent_kpis import build_agent_kpis
    payload = await build_agent_kpis(
        db, organization=organization, data_source=ds, model=model)
    return {"enabled": True, "kpis": payload}


@router.post("/data_sources/{data_source_id}/forecast")
async def rebuild_agent_forecast(
    data_source_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Forecast this agent's primary time series by LLM reasoning (BI-uplift
    Phase 7, Agent-Overview surface). Reuses the Auto-EDA time series, no ML
    engine, Claude reasoning preferred. No-op unless HYBRID_ADV_METHODS."""
    from app.settings.hybrid_flags import flags
    if not flags.ADV_METHODS:
        return {"enabled": False, "forecast": None}
    ds = (await db.execute(
        select(DataSource).where(
            DataSource.id == str(data_source_id),
            DataSource.organization_id == str(organization.id),
        )
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="not found")
    model = None
    try:
        from app.services.llm_service import LLMService
        model = await LLMService().get_default_model(db, organization)
    except Exception:
        model = None
    from app.services.analytics.agent_forecast import build_agent_forecast
    payload = await build_agent_forecast(
        db, organization=organization, data_source=ds, model=model)
    return {"enabled": True, "forecast": payload}


@router.post("/data_sources/{data_source_id}/repair")
async def repair_data_source(
    data_source_id: str,
    dry_run: bool = Query(False),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Self-heal an agent whose same-schema data got split across multiple
    physical staging tables (files uploaded in separate sessions). Stitches the
    orphan tables back into the agent's ONE bound table (idempotent, backup +
    transaction-safe). Owner-or-admin only. No-op unless HYBRID_INGEST_SELFHEAL.
    ``?dry_run=true`` reports what WOULD be stitched without changing anything."""
    from app.settings.hybrid_flags import flags
    if not flags.INGEST_SELFHEAL:
        return {"enabled": False, "report": None}
    ds = (await db.execute(
        select(DataSource).where(
            DataSource.id == str(data_source_id),
            DataSource.organization_id == str(organization.id),
        )
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="not found")
    # Owner-or-admin (mirrors the connector/curate guards elsewhere).
    allowed = bool(ds.owner_user_id and str(ds.owner_user_id) == str(current_user.id))
    if not allowed:
        try:
            from app.core.permission_resolver import resolve_permissions, FULL_ADMIN
            r = await resolve_permissions(db, str(current_user.id), str(organization.id))
            allowed = (FULL_ADMIN in r.org_permissions
                       or r.has_org_permission("manage_connections")
                       or r.has_org_permission("create_data_source"))
        except Exception:
            allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail="not allowed")
    from app.services.ingest.selfheal import selfheal_data_source
    report = await selfheal_data_source(
        db, organization=organization, data_source=ds,
        dry_run=bool(dry_run), drop_orphans=not bool(dry_run),
    )
    return {"enabled": True, "report": report}


@router.get("/memory/shared")
async def get_shared_memory(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Org-wide 'all agents' view: every reusable fact visible to the current
    user across the data sources they can access, grouped by scope. Access-gated
    (a user never sees a scope they don't hold). Empty unless HYBRID_SHARED_MEMORY."""
    from app.settings.hybrid_flags import flags
    if not flags.SHARED_MEMORY:
        return {"enabled": False, "groups": []}
    from app.services.knowledge import retrieve as R
    sources = await data_source_service.get_data_sources(db, current_user, organization)
    ds_ids = [str(getattr(s, "id", None) or (s.get("id") if isinstance(s, dict) else "")) for s in sources]
    ds_ids = [x for x in ds_ids if x]
    rows = await R.recall_items(
        db, organization_id=str(organization.id),
        current_user_id=str(current_user.id), data_source_ids=ds_ids,
    )
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r.scope_kind, r.scope_key)
        g = groups.setdefault(key, {"tier": _tier_of(r.scope_kind), "scope_kind": r.scope_kind, "scope_key": r.scope_key, "items": []})
        g["items"].append(_serialize_knowledge(r))
    # order: global first, then data, then personal
    order = {"global": 0, "data": 1, "personal": 2}
    grouped = sorted(groups.values(), key=lambda g: order.get(g["tier"], 1))
    return {"enabled": True, "groups": grouped}


async def _load_knowledge_row(db, kid: str, org_id: str):
    from sqlalchemy import select as _sel
    from app.models.agent_knowledge import AgentKnowledge
    return (await db.execute(_sel(AgentKnowledge).where(
        AgentKnowledge.id == str(kid),
        AgentKnowledge.organization_id == str(org_id),
        AgentKnowledge.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def _can_curate(db, row, current_user, organization) -> bool:
    """Org admin (full_admin / manage_connections) OR the fact's own creator."""
    if row.created_by_user_id and str(row.created_by_user_id) == str(current_user.id):
        return True
    try:
        from app.core.permission_resolver import resolve_permissions, FULL_ADMIN
        r = await resolve_permissions(db, str(current_user.id), str(organization.id))
        return FULL_ADMIN in r.org_permissions or r.has_org_permission("manage_connections")
    except Exception:
        return False


@router.delete("/memory/{knowledge_id}")
async def delete_memory(
    knowledge_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Soft-delete a learned fact (admin or its creator). Removes it from
    injection immediately."""
    from datetime import datetime
    row = await _load_knowledge_row(db, knowledge_id, str(organization.id))
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if not await _can_curate(db, row, current_user, organization):
        raise HTTPException(status_code=403, detail="not allowed")
    row.deleted_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.patch("/memory/{knowledge_id}")
async def patch_memory(
    knowledge_id: str,
    payload: dict = Body(default={}),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Demote/re-activate a fact (admin or creator). Body: {status:'pending'|'active'}."""
    row = await _load_knowledge_row(db, knowledge_id, str(organization.id))
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if not await _can_curate(db, row, current_user, organization):
        raise HTTPException(status_code=403, detail="not allowed")
    st = str((payload or {}).get("status") or "").strip()
    if st in ("pending", "active"):
        row.status = st
        await db.commit()
    return {"ok": True, "status": row.status}


@router.get("/memory/hot-assets")
async def get_hot_assets(
    threshold: int = Query(3, description="min verified_count to count as hot"),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Hot Shared-Memory query templates that are candidates to MATERIALIZE into
    a reusable asset (dash Engineer-style). Empty unless HYBRID_ASSET_MATERIALIZE."""
    from app.settings.hybrid_flags import flags
    if not flags.ASSET_MATERIALIZE:
        return {"enabled": False, "candidates": []}
    from app.services.knowledge import materialize as M
    cands = await M.hot_asset_candidates(db, organization_id=str(organization.id), threshold=int(threshold))
    return {"enabled": True, "candidates": cands}


@router.get("/data_sources/active", response_model=list[DataSourceListItemSchema])
async def get_active_data_sources(
    include_unconnected: bool = Query(False, description="Include user_required data sources the user hasn't connected yet (returned with user_status so the client can offer a Connect action)"),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    result = await data_source_service.get_active_data_sources(db, organization, current_user, include_unconnected=include_unconnected)
    await release_request_db(db)  # free the pooled connection before serialization (Cause A, Phase 1)
    return result

@router.get("/data_sources/{data_source_id}", response_model=DataSourceSchema)
@requires_resource_permission('data_source', 'view')
async def get_data_source(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization)
):
    return await data_source_service.get_data_source(db, data_source_id, organization, current_user)


@router.get("/data_sources/{data_source_type}/fields", response_model=dict)
async def get_data_source_fields(
    data_source_type: str,
    auth_policy: str = None,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db)
):
    return await data_source_service.get_data_source_fields(db, data_source_type, organization, current_user, auth_policy=auth_policy)

@router.post("/data_sources", response_model=DataSourceSchema)
@requires_permission('create_data_source')
async def create_data_source(
    data_source: DataSourceCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    # Check resource-level permission on connection(s) being linked
    connection_ids = []
    if data_source.connection_ids:
        connection_ids = data_source.connection_ids
    elif data_source.connection_id:
        connection_ids = [data_source.connection_id]
    if connection_ids:
        # #489 (flag CONNECTION_GRANTS): building an agent on an existing
        # connection requires per-connection `create_data_sources` (connection
        # admins & org `manage_connections` pass via implication). Flag OFF →
        # keeps the pre-#489 `manage_data_sources` check (byte-identical).
        from app.settings.hybrid_flags import flags as _hflags
        _conn_perm = "create_data_sources" if _hflags.CONNECTION_GRANTS else "manage_data_sources"
        await check_resource_permissions(
            db, str(current_user.id), str(organization.id),
            "connection", connection_ids, _conn_perm,
        )
    return await data_source_service.create_data_source(db, organization, current_user, data_source)


# --- Per-user private connector (HYBRID_PER_USER_CONNECTOR) ------------------
# Admin configures a connector template once; each member self-registers with
# their own credentials → a private per-user clone with their own synced catalog.
from pydantic import BaseModel as _BaseModel
from app.services import per_user_connector
from app.services import connector_sync


class _RegisterConnectorRequest(_BaseModel):
    auth_mode: str
    credentials: dict


@router.get("/connectors/available", response_model=list[dict])
async def list_available_connectors(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Connector templates the caller can self-register against."""
    return await per_user_connector.list_available_templates(db, organization)


@router.post("/connectors/{template_id}/register", response_model=DataSourceSchema)
async def register_connector(
    template_id: str,
    payload: _RegisterConnectorRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Register against a connector template with the caller's own credentials,
    creating a private per-user data source synced under their own token."""
    clone = await per_user_connector.register_template_for_user(
        db,
        template_id=template_id,
        organization=organization,
        user=current_user,
        auth_mode=payload.auth_mode,
        credentials=payload.credentials or {},
    )
    return await data_source_service.get_data_source(db, str(clone.id), organization, current_user)


class _TestTemplateRequest(_BaseModel):
    tenant_id: str
    server_hostname: Optional[str] = None


@router.post("/connectors/{key}/test-template", response_model=dict)
async def test_connector_template(
    key: str,
    payload: _TestTemplateRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Lightweight "test before save" for a Microsoft connector TEMPLATE (no
    credentials — only tenant_id + optional Fabric SQL endpoint). Validates
    GUID format + (for Fabric) endpoint format & DNS reachability. Fail-soft:
    ALWAYS returns 200 with {ok, reason}, never raises."""
    import re as _re
    import socket as _socket
    import asyncio as _asyncio

    _GUID_RE = _re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
    try:
        tenant_id = (payload.tenant_id or "").strip()
        if not _GUID_RE.match(tenant_id):
            return {"ok": False, "reason": "Tenant ID must be a valid GUID"}

        if key == "ms_fabric":
            raw = (payload.server_hostname or "").strip()
            if not raw:
                return {"ok": False, "reason": "Endpoint should be a *.fabric.microsoft.com hostname"}
            # Strip any scheme, path, and port the user may have pasted → host only.
            host = raw
            if "://" in host:
                host = host.split("://", 1)[1]
            host = host.split("/", 1)[0].split("\\", 1)[0]
            if host.startswith("[") and "]" in host:  # bracketed IPv6
                host = host[1:host.index("]")]
            else:
                host = host.split(":", 1)[0]
            host = host.strip().rstrip(".")
            if not host:
                return {"ok": False, "reason": "Endpoint should be a *.fabric.microsoft.com hostname"}
            well_formed = host.endswith(".datawarehouse.fabric.microsoft.com") or host.endswith(".fabric.microsoft.com")
            try:
                await _asyncio.to_thread(_socket.getaddrinfo, host, 1433)
            except Exception:
                return {"ok": False, "reason": "Endpoint hostname does not resolve"}
            if not well_formed:
                return {"ok": True, "reason": "Endpoint reachable · expected a *.fabric.microsoft.com hostname"}
            return {"ok": True, "reason": "Tenant ID valid · endpoint reachable"}

        # powerbi_user / sharepoint / onedrive — no endpoint, GUID check only.
        return {"ok": True, "reason": "Tenant ID looks valid"}
    except Exception as e:
        return {"ok": False, "reason": f"Could not validate: {str(e)[:120]}"}


# --- Connector Reports (admin) ---------------------------------------------
# Per connector-template usage rollup for Settings › Connectors › Reports.
# Admin-gated (full_admin / manage_connections), org-scoped, read-only.
async def _require_connector_admin(db, current_user, organization) -> None:
    from app.core.permission_resolver import resolve_permissions, FULL_ADMIN
    r = await resolve_permissions(db, str(current_user.id), str(organization.id))
    if not (FULL_ADMIN in r.org_permissions or r.has_org_permission("manage_connections")):
        raise HTTPException(status_code=403, detail="not allowed")


@router.get("/connectors/report", response_model=list)
async def get_connector_report(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Per-connector usage report: every user who connected each connector
    template, with question/token/cost/sync metrics (windowed to `days`)."""
    await _require_connector_admin(db, current_user, organization)
    from app.services import connector_report as _cr
    return await _cr.connector_report(db, str(organization.id), days=days)


@router.get("/connectors/report/{data_source_id}", response_model=dict)
async def get_connector_user_detail(
    data_source_id: str,
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Per-user connector detail: top questions, daily question sparkline (14d),
    token/cost/latency, sync history."""
    await _require_connector_admin(db, current_user, organization)
    from app.services import connector_report as _cr
    return await _cr.connector_user_detail(db, str(organization.id), data_source_id, days=days)


class _DeviceCodePollRequest(_BaseModel):
    device_code: str
    # Unified Microsoft sign-in (HYBRID_MS_UNIFIED_SIGNIN): also build a Fabric
    # sibling agent from the same token. Ignored when the flag is off.
    fanout: bool = False


@router.post("/connectors/{template_id}/device-code/start", response_model=dict)
async def connector_device_code_start(
    template_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Begin MFA-safe device-code sign-in against a Microsoft connector template."""
    return await per_user_connector.device_code_start(
        db, template_id=template_id, organization=organization
    )


@router.post("/connectors/{template_id}/device-code/poll", response_model=dict)
async def connector_device_code_poll(
    template_id: str,
    payload: _DeviceCodePollRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Poll once; on success auto-registers the caller's private clone and returns
    its data_source_id. Caller loops while status == 'pending'."""
    result = await per_user_connector.device_code_poll(
        db,
        template_id=template_id,
        organization=organization,
        user=current_user,
        device_code=payload.device_code,
        fanout=bool(getattr(payload, "fanout", False)),
    )
    # On a fresh sign-in, sync the clone in the background (discover tables →
    # seed → auto-learn description/starters/overview) while writing a live,
    # per-table sync log the FE can poll at GET /data_sources/{id}/sync-status.
    # Runs after the response so sign-in returns instantly. sync_clone_bg also
    # does the autolearn at the end, so it is not scheduled separately here.
    if result.get("status") == "success" and result.get("data_source_id"):
        _unified = bool(getattr(payload, "fanout", False))
        if _journey_v2() and not _unified:
            # Journey v2: DON'T auto-sync. Return the captured MS identity so the UI
            # shows "Connected as <email>" + a consent gate; the user then explicitly
            # calls POST /connectors/{data_source_id}/sync.
            result["needs_sync"] = True
        else:
            # Sync the Power BI clone AND any unified-sign-in Fabric sibling.
            # Unified sign-in implies consent (the user chose the combined tile), so
            # it auto-syncs both instead of showing the per-agent consent gate.
            for _ds_id in [result["data_source_id"], *result.get("sibling_data_source_ids", [])]:
                background_tasks.add_task(
                    per_user_connector.sync_clone_bg,
                    _ds_id,
                    str(organization.id),
                    str(current_user.id),
                )
    return result


class _ConnectRequest(_BaseModel):
    email: str
    password: str
    # Unified Microsoft sign-in (HYBRID_MS_UNIFIED_SIGNIN): also build a Fabric
    # sibling agent from the same token. Ignored when the flag is off.
    fanout: bool = False


@router.post("/connectors/{template_id}/connect", response_model=dict)
async def connector_connect(
    template_id: str,
    payload: _ConnectRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Adaptive sign-in: try email+password (ROPC); on MFA/policy, returns
    status='mfa_required' + a device_code the caller polls via
    /connectors/{id}/device-code/poll. On direct success, schedules the clone's
    background sync (discover → seed → learn) with a live pollable sync log."""
    result = await per_user_connector.connect(
        db,
        template_id=template_id,
        organization=organization,
        user=current_user,
        email=payload.email,
        password=payload.password,
        fanout=bool(getattr(payload, "fanout", False)),
    )
    if result.get("status") == "connected" and result.get("data_source_id"):
        _unified = bool(getattr(payload, "fanout", False))
        if _journey_v2() and not _unified:
            result["needs_sync"] = True
        else:
            # Sync the Power BI clone AND any unified-sign-in Fabric sibling.
            # Unified sign-in implies consent (combined tile) → auto-sync both.
            for _ds_id in [result["data_source_id"], *result.get("sibling_data_source_ids", [])]:
                background_tasks.add_task(
                    per_user_connector.sync_clone_bg,
                    _ds_id,
                    str(organization.id),
                    str(current_user.id),
                )
    return result


@router.post("/connectors/{data_source_id}/sync", response_model=dict)
async def connector_sync_now(
    data_source_id: str,
    background_tasks: BackgroundTasks,
    learn: bool = True,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Journey v2: start the clone's sync AFTER the user has confirmed identity +
    consented. Owner-gated (only the user who owns the private clone). Schedules
    sync_clone_bg (discover → seed → classify → learn) with the live pollable sync
    log. ``learn=false`` = re-discover only (refresh schema + relevance, skip the
    LLM re-training) — the cheap "Re-discover only" caret action. Re-training is
    also diff-gated inside sync_clone_bg, so a no-change sync never calls the LLM."""
    ds = (
        await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .where(DataSource.id == data_source_id,
                   DataSource.organization_id == str(organization.id),
                   DataSource.deleted_at.is_(None))
        )
    ).scalars().first()
    if ds is None:
        raise HTTPException(status_code=404, detail="Data agent not found")
    # owner check: the private clone's connection is owned by the caller (admins pass)
    owner_ok = False
    for c in (ds.connections or []):
        if str(getattr(c, "owner_user_id", "") or "") == str(current_user.id):
            owner_ok = True
            break
    if not owner_ok and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Only the connecting user can sync this agent")
    background_tasks.add_task(
        per_user_connector.sync_clone_bg,
        data_source_id,
        str(organization.id),
        str(current_user.id),
        learn,
        "manual",
    )
    return {"status": "syncing", "data_source_id": data_source_id, "learn": learn}


@router.get("/data_sources/{data_source_id}/sync-status", response_model=dict)
async def connector_sync_status(
    data_source_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Live per-clone connector sync log (CLI-style terminal). Returns {} when no
    run exists, else {phase, tables_total, tables_done, rows, log, error,
    updated_at}. Lightweight (single-row read); cross-worker safe (log in DB)."""
    run = await connector_sync.get_run(db, data_source_id)
    return run or {}


async def _assert_connector_owner(db, data_source_id: str, organization, current_user):
    """Load the clone + owner-gate (only the connecting user or a superuser)."""
    ds = (
        await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .where(DataSource.id == data_source_id,
                   DataSource.organization_id == str(organization.id),
                   DataSource.deleted_at.is_(None))
        )
    ).scalars().first()
    if ds is None:
        raise HTTPException(status_code=404, detail="Data agent not found")
    owner_ok = any(
        str(getattr(c, "owner_user_id", "") or "") == str(current_user.id)
        for c in (ds.connections or [])
    )
    if not owner_ok and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Only the connecting user can manage this agent")
    return ds


@router.get("/connectors/{data_source_id}/auto_sync", response_model=dict)
async def get_connector_auto_sync(
    data_source_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Per-agent scheduled auto-sync config: {enabled, interval_hours, last_sync_at}."""
    from app.services.scheduled_connector_sync import get_config
    return await get_config(db, str(organization.id), data_source_id)


@router.put("/connectors/{data_source_id}/auto_sync", response_model=dict)
async def set_connector_auto_sync(
    data_source_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Enable/disable scheduled auto-sync for this agent + set the interval (hours,
    clamped 1..168). Owner-gated. Re-training on each run is diff-gated, so an
    unchanged schema costs nothing."""
    await _assert_connector_owner(db, data_source_id, organization, current_user)
    from app.services.scheduled_connector_sync import set_config
    return await set_config(
        db, str(organization.id), data_source_id,
        bool(payload.get("enabled")),
        int(payload.get("interval_hours") or 24),
    )


@router.delete("/data_sources/{data_source_id}")
@requires_resource_permission('data_source', 'manage')
async def delete_data_source(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization)
):
    return await data_source_service.delete_data_source(db, data_source_id, organization, current_user)

@router.get("/data_sources/{data_source_id}/test_connection", response_model=dict)
@requires_resource_permission('data_source', 'view')
async def test_data_source_connection(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization)
):
    return await data_source_service.test_data_source_connection(db, data_source_id, organization, current_user)

@router.post("/data_sources/test_connection", response_model=dict)
@requires_permission('create_data_source')
async def test_new_data_source_connection(
    data_source: DataSourceCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await data_source_service.test_new_data_source_connection(db=db, data=data_source, organization=organization, current_user=current_user)

@router.put("/data_sources/{data_source_id}", response_model=DataSourceSchema)
@requires_resource_permission('data_source', 'manage')
async def update_data_source(
    data_source_id: str,
    data_source: DataSourceUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization)
):
    return await data_source_service.update_data_source(db, data_source_id, organization, data_source, current_user)

@router.get("/data_sources/{data_source_id}/schema", response_model=list)
@requires_resource_permission('data_source', 'view')
async def get_data_source_schema(
    data_source_id: str,
    with_stats: bool = Query(False),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.get_data_source_schema(db, data_source_id, include_inactive=False, organization=organization, current_user=current_user, with_stats=with_stats)

@router.get("/data_sources/{data_source_id}/full_schema", response_model=Union[PaginatedTablesResponse, list])
@requires_resource_permission('data_source', 'view_schema')
async def get_data_source_full_schema(
    data_source_id: str,
    with_stats: bool = Query(False),
    # Pagination params (optional - if not provided, returns legacy list response)
    page: Optional[int] = Query(None, ge=1, description="Page number (1-indexed)"),
    page_size: Optional[int] = Query(None, ge=1, le=500, description="Items per page (max 500)"),
    schema_filter: Optional[str] = Query(None, description="Comma-separated schema names to filter"),
    connection_filter: Optional[str] = Query(None, description="Comma-separated connection IDs to filter"),
    search: Optional[str] = Query(None, description="Search tables by name"),
    sort_by: str = Query("name", description="Sort by: name, centrality_score, is_active, richness"),
    sort_dir: str = Query("asc", description="Sort direction: asc or desc"),
    selected_state: Optional[str] = Query(None, description="Filter by selection state: 'selected' or 'unselected'"),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    # If pagination params provided, use paginated response
    if page is not None or page_size is not None:
        # Default pagination values
        page = page or 1
        page_size = page_size or 100

        # Parse schema filter (comma-separated string to list)
        schema_filter_list = None
        if schema_filter:
            schema_filter_list = [s.strip() for s in schema_filter.split(",") if s.strip()]

        # Parse connection filter (comma-separated string to list)
        connection_filter_list = None
        if connection_filter:
            connection_filter_list = [c.strip() for c in connection_filter.split(",") if c.strip()]

        paginated = await data_source_service.get_data_source_schema_paginated(
            db=db,
            data_source_id=data_source_id,
            organization=organization,
            page=page,
            page_size=page_size,
            schema_filter=schema_filter_list,
            connection_filter=connection_filter_list,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            include_inactive=True,
            selected_state=selected_state,
            with_stats=with_stats,
            current_user=current_user,
        )
        await release_request_db(db)  # free the pooled connection before serialization (Cause A, Phase 1)
        return paginated

    # Legacy behavior: return full list
    legacy = await data_source_service.get_data_source_schema(db, data_source_id, include_inactive=True, organization=organization, current_user=current_user, with_stats=with_stats)
    await release_request_db(db)  # free the pooled connection before serialization (Cause A, Phase 1)
    return legacy


@router.get("/data_sources/{data_source_id}/overview")
@requires_resource_permission('data_source', 'view_schema')
async def get_data_source_overview(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    """GROUNDED agent-knowledge for the redesigned agent Overview page.

    Every field is derived from real DB data (schema tables, real FKs, approved
    semantic descriptions). NO fabrication. Flag-gated (HYBRID_CONNECTOR_JOURNEY_V2)
    and fully fail-soft — never 500s on a data issue, returns partial instead.
    """
    import logging
    _log = logging.getLogger(__name__)

    if not _journey_v2():
        return {}

    # Serve a cached overview if fresh (the whole cost is recomputing the schema).
    _uid = str(getattr(current_user, "id", "") or "")
    _cached = _overview_cache_get(str(data_source_id), _uid)
    if _cached is not None:
        return _cached
    _t0 = _time.monotonic()

    empty = {
        "stats": {"active_tables": 0, "total_columns": 0, "connections": 0},
        "tables": [],
        "joins": [],
        "view_only": [],
    }

    # --- Load the data source (for connection count) ------------------------
    try:
        ds_result = await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .filter(DataSource.id == data_source_id, DataSource.organization_id == organization.id)
        )
        data_source = ds_result.scalar_one_or_none()
    except Exception:
        _log.exception("overview: failed loading data source %s", data_source_id)
        data_source = None
    if data_source is None:
        return empty
    conn_count = len(data_source.connections or [])
    empty["stats"]["connections"] = conn_count

    # HOT START: fire a background pre-warm of this user's Power BI model so their
    # first real query is a cache hit instead of a cold 40-84s query. Fire-and-forget,
    # flag-gated inside, throttled per (data_source, user), never blocks this response.
    try:
        from app.services.connector_warm import schedule_warm
        schedule_warm(str(data_source_id), str(organization.id), _uid)
    except Exception:
        pass

    # --- Load ALL tables (same path /full_schema legacy uses) ---------------
    try:
        all_tables = await data_source_service.get_data_source_schema(
            db, data_source_id, include_inactive=True,
            organization=organization, current_user=current_user, with_stats=False,
        )
    except Exception:
        _log.exception("overview: failed loading schema for %s", data_source_id)
        return empty

    # --- Approved semantic descriptions (fallback purpose source) -----------
    semantic_desc = {}
    try:
        from app.models.semantic_table import SemanticTable
        sem_result = await db.execute(
            select(SemanticTable).filter(
                SemanticTable.organization_id == organization.id,
                SemanticTable.data_source_id == data_source_id,
                SemanticTable.status == 'approved',
                SemanticTable.invalid_at.is_(None),
            )
        )
        for row in sem_result.scalars().all():
            d = (row.description or '').strip()
            if d and row.table_name not in semantic_desc:
                semantic_desc[row.table_name] = d
    except Exception:
        _log.exception("overview: failed loading semantic descriptions for %s", data_source_id)

    active = []
    try:
        active = [t for t in (all_tables or []) if getattr(t, 'is_active', False)]
    except Exception:
        _log.exception("overview: failed filtering active tables for %s", data_source_id)
        active = []

    # --- stats ---------------------------------------------------------------
    total_columns = 0
    for t in active:
        try:
            total_columns += len(getattr(t, 'columns', None) or [])
        except Exception:
            pass

    # --- tables (sorted by centrality desc, None last, cap 40) --------------
    tables_out = []
    try:
        def _cent(t):
            c = getattr(t, 'centrality_score', None)
            return c if c is not None else float('-inf')
        ordered = sorted(active, key=_cent, reverse=True)[:40]
        for t in ordered:
            name = getattr(t, 'name', None)
            col_count = len(getattr(t, 'columns', None) or [])
            row_count = getattr(t, 'no_rows', None) or 0
            centrality = getattr(t, 'centrality_score', None)
            entity_like = bool(getattr(t, 'entity_like', False))
            # purpose: metadata_json.description first, else approved semantic layer
            purpose = None
            meta = getattr(t, 'metadata_json', None) or {}
            if isinstance(meta, dict):
                md = (meta.get('description') or '').strip() if meta.get('description') else ''
                if md:
                    purpose = md
            if not purpose:
                purpose = semantic_desc.get(name) or None
            tables_out.append({
                "name": name,
                "column_count": col_count,
                "row_count": row_count,
                "entity_like": entity_like,
                "centrality": centrality,
                "purpose": purpose,
            })
    except Exception:
        _log.exception("overview: failed building tables for %s", data_source_id)
        tables_out = []

    # --- joins from REAL foreign keys (dedup, cap 30) -----------------------
    joins_out = []
    try:
        seen = set()
        for t in active:
            fks = getattr(t, 'fks', None) or []
            for fk in fks:
                try:
                    col = fk.get('column') or {}
                    ref_col = fk.get('references_column') or {}
                    tup = (
                        getattr(t, 'name', None),
                        col.get('name'),
                        fk.get('references_name'),
                        ref_col.get('name'),
                    )
                    if None in tup or tup in seen:
                        continue
                    seen.add(tup)
                    joins_out.append({
                        "from_table": tup[0],
                        "from_column": tup[1],
                        "to_table": tup[2],
                        "to_column": tup[3],
                    })
                    if len(joins_out) >= 30:
                        break
                except Exception:
                    continue
            if len(joins_out) >= 30:
                break
    except Exception:
        _log.exception("overview: failed building joins for %s", data_source_id)
        joins_out = []

    # --- view_only: only trivially-available stored source ------------------
    # Live Power BI clients stash view-only datasets on the client instance
    # (_last_view_only). Constructing a live client here is slow / 429-prone,
    # so we do NOT — empty is a correct, FE-handled answer.
    view_only_out = []

    payload = {
        "stats": {
            "active_tables": len(active),
            "total_columns": total_columns,
            "connections": conn_count,
        },
        "tables": tables_out,
        "joins": joins_out,
        "view_only": view_only_out,
    }
    _overview_cache_put(str(data_source_id), _uid, payload)
    _log.info("overview: built ds=%s in %.0fms tables=%d (cached %.0fs)",
              data_source_id, (_time.monotonic() - _t0) * 1000.0, len(active), _OVERVIEW_TTL)
    return payload


@router.post("/data_sources/{data_source_id}/regenerate-starters")
@requires_resource_permission('data_source', 'manage')
async def regenerate_data_source_starters(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    """STARTER_REFRESH (flag HYBRID_STARTER_REFRESH): re-run the schema-grounded
    conversation-starter generator on demand from the agent Overview.

    Reuses the existing service generator; persists + returns the fresh starters.
    Fail-soft — on any generator error, returns 200 with the EXISTING starters
    unchanged (the Refresh button must never 500)."""
    import logging
    _log = logging.getLogger(__name__)

    from app.settings.hybrid_flags import flags
    if not flags.STARTER_REFRESH:
        raise HTTPException(status_code=404, detail="Not found")

    # Load the data source (org-scoped, same auth as siblings).
    ds_result = await db.execute(
        select(DataSource).filter(
            DataSource.id == data_source_id,
            DataSource.organization_id == organization.id,
        )
    )
    data_source = ds_result.scalar_one_or_none()
    if data_source is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    existing = list(data_source.conversation_starters or [])

    try:
        generated = await data_source_service.generate_data_source_items(
            db=db,
            item="conversation_starters",
            data_source_id=data_source_id,
            organization=organization,
            current_user=current_user,
        )
        starters = (generated or {}).get("conversation_starters")
        if starters is not None:
            data_source.conversation_starters = starters
            await db.commit()
            await db.refresh(data_source)
            return {"conversation_starters": list(data_source.conversation_starters or [])}
    except Exception:
        _log.exception("regenerate-starters: generation failed for %s", data_source_id)
        try:
            await db.rollback()
        except Exception:
            pass

    # Generator returned nothing usable, or failed — keep the existing starters.
    return {"conversation_starters": existing}


@router.get("/data_sources/{data_source_id}/headline")
@requires_resource_permission('data_source', 'view_schema')
async def get_data_source_headline(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    """HOT START: the user's headline KPIs (the model's own measures), computed on
    THEIR client and cached per (data_source, user). Returns {status, items:[{label,
    value}]}. STALE-WHILE-REVALIDATE — this request path NEVER runs the 20-40s live
    DAX inline: it serves the cached value instantly if present (refreshing behind
    the scenes when stale), or returns {status:"warming"} and kicks a background warm
    when there's no cache yet. Fail-soft — returns an empty list rather than 500."""
    try:
        from app.services.connector_warm import headline_fast
        return await headline_fast(str(data_source_id), str(organization.id), str(current_user.id))
    except Exception:
        return {"status": "error", "items": []}


@router.put("/data_sources/{data_source_id}/update_schema", response_model=DataSourceSchema)
@requires_resource_permission('data_source', 'view_schema')
async def update_table_status_in_schema(
    data_source_id: str,
    tables: list[DataSourceTableSchema],
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.update_table_status_in_schema(db, data_source_id, tables, organization)


@router.post("/data_sources/{data_source_id}/bulk_update_tables", response_model=DeltaUpdateTablesResponse)
@requires_resource_permission('data_source', 'view_schema')
async def bulk_update_tables(
    data_source_id: str,
    request: BulkUpdateTablesRequest,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    """
    Bulk activate/deactivate tables matching filter criteria.
    
    - action: "activate" or "deactivate"
    - filter: {"schema": ["schema1", "schema2"], "search": "pattern"}
    """
    return await data_source_service.bulk_update_tables_status(
        db=db,
        data_source_id=data_source_id,
        organization=organization,
        action=request.action,
        filter_params=request.filter,
        current_user=current_user,
    )


@router.put("/data_sources/{data_source_id}/update_tables_status", response_model=DeltaUpdateTablesResponse)
@requires_resource_permission('data_source', 'view_schema')
async def update_tables_status_delta(
    data_source_id: str,
    request: DeltaUpdateTablesRequest,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    """
    Update table is_active status using delta (efficient for large table counts).
    
    - activate: list of table names to set is_active=True
    - deactivate: list of table names to set is_active=False
    """
    return await data_source_service.update_tables_status_delta(
        db=db,
        data_source_id=data_source_id,
        organization=organization,
        activate=request.activate,
        deactivate=request.deactivate,
        current_user=current_user,
    )


@router.get("/data_sources/{data_source_id}/generate_items", response_model=dict)
@requires_resource_permission('data_source', 'manage')
async def generate_data_source_items(
    data_source_id: str,
    item: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.generate_data_source_items(db, item, data_source_id, organization, current_user)

@router.post("/data_sources/{data_source_id}/llm_sync", response_model=dict)
@requires_resource_permission('data_source', 'manage')
async def llm_sync(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.llm_sync(db=db, data_source_id=data_source_id, organization=organization, current_user=current_user)

@router.get("/data_sources/{data_source_id}/refresh_schema", response_model=list)
@requires_resource_permission('data_source', 'view_schema')
async def refresh_data_source_schema(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.refresh_data_source_schema(db, data_source_id, organization, current_user)

@router.get("/data_sources/{data_source_id}/metadata_resources", response_model=MetadataIndexingJobSchema)
@requires_resource_permission('data_source', 'view')
async def get_metadata_resources(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.get_metadata_resources(db, data_source_id, organization, current_user)

@router.put("/data_sources/{data_source_id}/update_metadata_resources", response_model=MetadataIndexingJobSchema)
@requires_resource_permission('data_source', 'manage')
async def update_metadata_resources(
    data_source_id: str,
    resources: list = Body(...),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    """Update the active status of metadata resources for a data source"""
    return await data_source_service.update_resources_status(
        db=db,
        data_source_id=data_source_id,
        resources=resources,
        organization=organization,
        current_user=current_user
    )


@router.get("/data_sources/{data_source_id}/members", response_model=list[DataSourceMembershipSchema])
@requires_resource_permission('data_source', 'view')
async def get_data_source_members(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.get_data_source_members(db, data_source_id, organization, current_user)

@router.post("/data_sources/{data_source_id}/members", response_model=DataSourceMembershipSchema)
@requires_resource_permission('data_source', 'manage')
async def add_data_source_member(
    data_source_id: str,
    member: DataSourceMembershipCreate,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.add_data_source_member(db, data_source_id, member, organization, current_user)

@router.delete("/data_sources/{data_source_id}/members/{user_id}", status_code=204)
@requires_resource_permission('data_source', 'manage')
async def remove_data_source_member(
    data_source_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    return await data_source_service.remove_data_source_member(db, data_source_id, user_id, organization, current_user)


# ==================== Domain-Connection Routes ====================

@router.get("/data_sources/{data_source_id}/connections")
@requires_resource_permission('data_source', 'manage')
async def get_domain_connections(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    """Get all connections linked to an agent."""
    connections = await data_source_service.get_domain_connections(db, data_source_id, organization)
    return [
        {
            "id": str(conn.id),
            "name": conn.name,
            "type": conn.type,
            "is_active": conn.is_active,
        }
        for conn in connections
    ]


@router.post("/data_sources/{data_source_id}/connections/{connection_id}")
@requires_resource_permission('data_source', 'manage')
async def add_connection_to_domain(
    data_source_id: str,
    connection_id: str,
    sync_tables: bool = True,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    """Add a connection to an agent (M:N relationship)."""
    return await data_source_service.add_connection_to_domain(
        db=db,
        data_source_id=data_source_id,
        connection_id=connection_id,
        organization=organization,
        current_user=current_user,
        sync_tables=sync_tables,
    )


@router.delete("/data_sources/{data_source_id}/connections/{connection_id}")
@requires_resource_permission('data_source', 'manage')
async def remove_connection_from_domain(
    data_source_id: str,
    connection_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user)
):
    """Remove a connection from an agent."""
    return await data_source_service.remove_connection_from_domain(
        db=db,
        data_source_id=data_source_id,
        connection_id=connection_id,
        organization=organization,
        current_user=current_user,
    )