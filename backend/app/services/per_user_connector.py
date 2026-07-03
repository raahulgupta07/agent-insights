"""Per-user private connector (HYBRID_PER_USER_CONNECTOR).

Admin configures a connector ONCE as a TEMPLATE (a DataSource with
`is_user_template=True` — tenant/client config on its Connection, NO user creds,
NO synced data). Each member then *registers* against that template with their
own credentials. Registration CLONES the template into a private, owner-scoped
DataSource (+ its own Connection) and syncs the catalog under the member's own
token — so every user gets ONLY the tables their account can see, private to
them (`is_public=False` + `owner_user_id` + the source's own access control).

Isolation is triple-gated and reuses primitives that already exist:
  * new private Connection (owner_user_id=user) carrying the user's OWN creds
    (Fernet at rest) — 1:1 with the user, so no shared/system credentials
  * refresh_schema — catalog fetched under the user's own credentials
  * is_public=False + owner membership — clone visible only to its owner

Everything here is additive + fail-soft; the template row is never mutated.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models.data_source import DataSource
from app.models.connection import Connection
from app.models.organization import Organization
from app.models.user import User
from app.settings.hybrid_flags import flags

logger = logging.getLogger(__name__)


def _ms_identity_from_token(token_res: dict) -> dict:
    """Decode the MS id_token from a token response into a durable identity dict
    (CONNECTOR_JOURNEY_V2). Returns {} when the flag is OFF or nothing decodes —
    fully fail-soft so it can never break the connect flow. Never logs claims."""
    if not flags.CONNECTOR_JOURNEY_V2:
        return {}
    try:
        from app.services import powerbi_device_code as dc
        claims = dc.decode_id_token((token_res or {}).get("id_token") or "")
        if not claims:
            return {}
        from datetime import datetime, timezone
        out: dict = {"connected_at": datetime.now(timezone.utc).isoformat()}
        email = claims.get("preferred_username")
        if email:
            out["ms_account_email"] = email
        name = claims.get("name")
        if name:
            out["ms_account_name"] = name
        tid = claims.get("tid")
        if tid:
            out["ms_tenant_id"] = tid
        return out
    except Exception:  # noqa: BLE001
        return {}


def _merge_ms_identity_into_config(conn, ms_identity: dict) -> None:
    """Merge the captured MS identity into a connection's config JSON (the same
    durable, non-secret store that already holds tenant_id), without clobbering
    existing keys. Fail-soft: any error is swallowed so connect never breaks."""
    if not ms_identity:
        return
    try:
        cfg = conn.config
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        cfg = dict(cfg or {})
        cfg.update(ms_identity)  # identity keys merge over; tenant_id etc. preserved
        # Store the dict directly. The `config` column is a JSON type, so assigning a
        # `json.dumps(...)` STRING double-encodes it (`"{...}"`) and breaks SQL-level
        # matching (config::jsonb->>'email' returns null). A fresh dict object is a new
        # ref, so SQLAlchemy detects the change without flag_modified.
        conn.config = cfg
    except Exception:  # noqa: BLE001
        pass


async def list_available_templates(db, organization: Organization) -> list[dict]:
    """Templates a member can self-register against (admin-published shells)."""
    if not flags.PER_USER_CONNECTOR:
        return []
    rows = (
        await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .where(
                DataSource.organization_id == str(organization.id),
                DataSource.is_user_template.is_(True),
            )
        )
    ).scalars().all()

    out: list[dict] = []
    for ds in rows:
        if (getattr(ds, "publish_status", "published") or "published") == "disabled":
            continue
        conn = ds.connections[0] if ds.connections else None
        out.append({
            "id": str(ds.id),
            "name": ds.name,
            "description": ds.description or "",
            "type": conn.type if conn else None,
            "auth_policy": conn.auth_policy if conn else None,
            "allowed_user_auth_modes": (conn.allowed_user_auth_modes if conn else None) or [],
        })
    return out


def _conn_account_email(conn) -> str:
    """The Power BI / MS account email stored on a clone's connection config
    (ms_identity: email/upn) or its username credential-hint. Lowercased. '' if none."""
    try:
        import json as _json
        cfg = conn.config
        if isinstance(cfg, str):
            cfg = _json.loads(cfg) if cfg else {}
        cfg = cfg or {}
        return str(
            cfg.get("email")
            or cfg.get("ms_account_email")
            or cfg.get("upn")
            or cfg.get("preferred_username")
            or cfg.get("username")
            or ""
        ).strip().lower()
    except Exception:
        return ""


async def _existing_clone(db, *, template_id: str, user_id: str, pbi_email: str = None) -> Optional[DataSource]:
    """Find this user's private clone of a template. When ``pbi_email`` is given,
    match ONLY a clone whose connection is for that same MS/Power BI account — so a
    DIFFERENT account makes a NEW agent instead of overwriting, and the SAME account
    re-syncs the existing one. When omitted, falls back to the first clone (legacy)."""
    clones = (
        await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .where(
                DataSource.template_source_id == str(template_id),
                DataSource.owner_user_id == str(user_id),
            )
        )
    ).scalars().all()
    if not clones:
        return None
    if not pbi_email:
        return clones[0]
    want = str(pbi_email).strip().lower()
    # 1) config-stamped account email (new clones)
    for c in clones:
        for conn in (c.connections or []):
            if _conn_account_email(conn) == want:
                return c
    # 2) legacy clones (no stamped email) — match by the "· <email>" name suffix so
    #    reconnecting the same account re-syncs instead of colliding on the name.
    for c in clones:
        nm = (c.name or "").strip().lower()
        if nm.endswith("· " + want) or nm == want or ("· " + want + " (") in nm:
            return c
    return None  # same user, different account → caller creates a new agent


def _strip_name_suffix(name: str) -> str:
    """Drop a trailing ` (N)` collision suffix so '... · a@b (2)' == '... · a@b'."""
    import re
    return re.sub(r"\s*\(\d+\)\s*$", "", str(name or "")).strip().lower()


async def _find_reusable_connection(
    db, *, user_id: str, conn_type: str, base_name: str, pbi_email: str
):
    """Find an owner-private connection this user already owns that we can ADOPT
    instead of creating a new one — so reconnecting the same account never spawns
    a duplicate ` (2)` connection. Matches by stamped account email first, then by
    the base name (ignoring any ` (N)` suffix). Prefers a connection not linked to
    any live DataSource (an orphan left by a prior delete), else any match. Returns
    the Connection or None. Fail-soft."""
    try:
        from app.models.domain_connection import DomainConnection
    except Exception:
        DomainConnection = None
    try:
        conns = (
            await db.execute(
                select(Connection).where(
                    Connection.owner_user_id == str(user_id),
                    Connection.type == conn_type,
                )
            )
        ).scalars().all()
    except Exception:
        return None
    if not conns:
        return None
    want_email = str(pbi_email or "").strip().lower()
    want_base = _strip_name_suffix(base_name)

    def _matches(c) -> bool:
        if want_email and _conn_account_email(c) == want_email:
            return True
        return _strip_name_suffix(c.name) == want_base

    candidates = [c for c in conns if _matches(c)]
    if not candidates:
        return None

    # Which candidates are orphaned (no live DataSource link)? Prefer those.
    linked_ids: set = set()
    if DomainConnection is not None:
        try:
            rows = (
                await db.execute(
                    select(DomainConnection.connection_id).where(
                        DomainConnection.connection_id.in_([str(c.id) for c in candidates])
                    )
                )
            ).scalars().all()
            linked_ids = {str(r) for r in rows}
        except Exception:
            linked_ids = set()
    orphans = [c for c in candidates if str(c.id) not in linked_ids]
    return (orphans[0] if orphans else candidates[0])


async def register_template_for_user(
    db,
    *,
    template_id: str,
    organization: Organization,
    user: User,
    auth_mode: str,
    credentials: dict,
    defer_sync: bool = False,
    ms_identity: Optional[dict] = None,
) -> DataSource:
    """Clone a template into a private data source for `user` and sync under
    their own credentials. Idempotent per (template, user): re-registering
    updates the stored credentials and re-syncs the same private clone.

    When `defer_sync=True` do steps 1-3 (connection + clone + membership) and
    return the clone shell immediately — the caller schedules `sync_clone_bg`
    to run step 4 (refresh_schema + seed + autolearn) as a background task with
    its own live sync log. `defer_sync=False` keeps the legacy inline-sync
    behavior (used by the `/register` route)."""
    if not flags.PER_USER_CONNECTOR:
        raise HTTPException(status_code=404, detail="Per-user connector is not enabled")

    # Capture primitives up-front — the commits below expire ORM objects (greenlet).
    org_id = str(organization.id)
    user_id = str(user.id)

    template = (
        await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .where(
                DataSource.id == str(template_id),
                DataSource.organization_id == org_id,
            )
        )
    ).scalars().first()
    if not template or not template.is_user_template:
        raise HTTPException(status_code=404, detail="Connector template not found")
    if not template.connections:
        raise HTTPException(status_code=400, detail="Connector template has no connection")

    tmpl_conn = template.connections[0]
    conn_type = tmpl_conn.type
    tmpl_config = tmpl_conn.config
    if isinstance(tmpl_config, str):
        try:
            tmpl_config = json.loads(tmpl_config)
        except Exception:
            tmpl_config = {}
    tmpl_config = dict(tmpl_config or {})
    tmpl_name = template.name
    creds = dict(credentials or {})

    # Identify the actual Power BI / MS ACCOUNT being connected (the email the user
    # typed), NOT the app-login email. This is what names the agent and decides
    # whether a repeat connect re-syncs the same account or creates a new agent for
    # a different account.
    _mi = ms_identity or {}
    pbi_email = (
        str(
            (_mi.get("ms_account_email") or "")
            or (_mi.get("email") or "")
            or (_mi.get("upn") or "")
            or (_mi.get("preferred_username") or "")
            or (creds.get("username") or "")
        ).strip()
        or (user.email or "")
        or str(user_id)[:8]
    )

    # The per-user clone connection is 1:1 private to this user, so we store the
    # user's OWN credentials directly on it as system_only creds (Fernet at rest).
    # This is what refresh_schema (connection-level) AND the chat credential
    # resolver both read — no two-level per-user credential dance needed. The
    # data is still fully isolated: the connection is owner_user_id-private and
    # only this user's is_public=False DataSource points to it.

    # Re-registration of the SAME account → reuse that private clone (re-sync).
    # A DIFFERENT account → _existing_clone returns None → a new agent is created
    # below, named after this account, so the two never collide.
    clone = await _existing_clone(
        db, template_id=str(template_id), user_id=user_id, pbi_email=pbi_email
    )
    if clone is not None:
        new_conn = clone.connections[0] if clone.connections else None
        if new_conn is not None and creds:
            new_conn.credentials = None
            new_conn.encrypt_credentials(creds)
            new_conn.auth_policy = "system_only"
            # Capture the signed-in MS identity (CONNECTOR_JOURNEY_V2) onto the
            # connection config so it's durable + shown in the UI, and always stamp
            # the account email so a future connect can match this exact account.
            _merge_ms_identity_into_config(new_conn, {**(ms_identity or {}), "email": pbi_email})
            db.add(new_conn)
            await db.commit()
            await db.refresh(new_conn)
    else:
        # 1. Private per-user connection carrying the user's own credentials.
        #    system_only → create_connection validates them up-front (bad creds
        #    surface as a 400 to the user) and kicks off catalog indexing.
        from app.services.connection_service import ConnectionService
        conn_svc = ConnectionService()
        base_name = f"{tmpl_name} · {pbi_email}"
        new_conn = None

        # Adopt an existing owner-private connection for this account (e.g. an orphan
        # left by a prior agent delete) instead of creating a new one — prevents the
        # duplicate ` (2)` connection that a base-name collision would otherwise force.
        adopt = await _find_reusable_connection(
            db, user_id=user_id, conn_type=conn_type, base_name=base_name, pbi_email=pbi_email
        )
        if adopt is not None:
            try:
                adopt.credentials = None
                adopt.encrypt_credentials(creds)
                adopt.auth_policy = "system_only"
                adopt.owner_user_id = user_id
                _merge_ms_identity_into_config(adopt, {**(ms_identity or {}), "email": pbi_email})
                # Normalise the name back to the clean base (drop any ` (N)`); on a
                # residual name clash keep the current name rather than fail.
                if _strip_name_suffix(adopt.name) == _strip_name_suffix(base_name):
                    adopt.name = base_name
                db.add(adopt)
                await db.commit()
                await db.refresh(adopt)
                new_conn = adopt
            except IntegrityError:
                await db.rollback()
                new_conn = None  # fall through to create a fresh connection
            except Exception as e:  # noqa: BLE001
                logger.warning("per_user_connector: adopt connection failed: %s", e)
                try:
                    await db.rollback()
                except Exception:
                    pass
                new_conn = None

        for attempt in range(4):
            if new_conn is not None:
                break
            name_try = base_name if attempt == 0 else f"{base_name} ({attempt+1})"
            try:
                new_conn = await conn_svc.create_connection(
                    db=db,
                    organization=organization,
                    current_user=user,
                    name=name_try,
                    type=conn_type,
                    config=dict(tmpl_config),
                    credentials=creds,
                    auth_policy="system_only",
                    owner_user_id=user_id,
                    # Identity already proven via device-code; tolerate an empty /
                    # non-queryable catalog at connect (Power BI on-prem datasets,
                    # etc.). The catalog syncs best-effort below.
                    validate=False,
                )
                break
            except HTTPException as e:
                if e.status_code == 409 and attempt < 3:
                    continue
                raise
        if new_conn is None:
            raise HTTPException(status_code=409, detail="Could not create your connection")

        # Capture the signed-in MS identity (CONNECTOR_JOURNEY_V2) onto the new
        # connection's config so it's durable + shown in the UI, and ALWAYS stamp
        # the account email (even for ROPC where ms_identity is empty) so a repeat
        # connect can match this exact account and re-sync instead of duplicating.
        if True:
            _merge_ms_identity_into_config(new_conn, {**(ms_identity or {}), "email": pbi_email})
            db.add(new_conn)
            try:
                await db.commit()
                await db.refresh(new_conn)
            except Exception as e:  # noqa: BLE001
                logger.warning("per_user_connector: ms identity stamp failed: %s", e)
                try:
                    await db.rollback()
                except Exception:
                    pass

        # 2. Private, owner-scoped DataSource clone bound to that connection.
        clone = None
        for attempt in range(4):
            ds_name = base_name if attempt == 0 else f"{base_name} ({attempt+1})"
            clone = DataSource(
                name=ds_name,
                organization_id=org_id,
                owner_user_id=user_id,
                is_public=False,
                is_user_template=False,
                template_source_id=str(template_id),
                # Auto-learn ON: after the catalog syncs, a background task runs
                # llm_sync() to generate the description + conversation starters +
                # a primary "overview" instruction — same as the manual wizard's
                # "Use LLM to learn agent". See autolearn_clone() below.
                use_llm_sync=True,
            )
            clone.connections.append(new_conn)
            db.add(clone)
            try:
                await db.commit()
                await db.refresh(clone)
                break
            except IntegrityError:
                await db.rollback()
                clone = None
        if clone is None:
            raise HTTPException(status_code=409, detail="Could not create your private data source")

        # 3. Owner membership so it appears in the owner's agents list.
        try:
            from app.services.data_source_service import DataSourceService
            await DataSourceService()._create_memberships(db, clone, [user_id], permissions=["manage"])
        except Exception as e:
            logger.warning("per_user_connector: membership create failed: %s", e)

    # 4. Sync the catalog under the user's own creds → private per-user tables.
    clone_id = str(clone.id)
    if defer_sync:
        # Return the clone shell now; the caller schedules sync_clone_bg() to do
        # the refresh_schema + seed + autolearn in the background with a live log.
        return (
            await db.execute(
                select(DataSource)
                .options(selectinload(DataSource.connections))
                .where(DataSource.id == clone_id)
            )
        ).scalars().first()
    if new_conn is not None:
        try:
            from app.services.connection_service import ConnectionService
            await ConnectionService().refresh_schema(db, new_conn, current_user=user)
            # Seed DataSourceTable from the freshly-synced ConnectionTable catalog.
            fresh = (
                await db.execute(
                    select(DataSource)
                    .options(selectinload(DataSource.connections))
                    .where(DataSource.id == clone_id)
                )
            ).scalars().first()
            if fresh and fresh.connections:
                await DataSourceService_seed(db, fresh, fresh.connections[0])
        except Exception as e:
            # Fail-soft: the clone + creds exist; the user can re-sync from the UI.
            logger.warning("per_user_connector: initial sync failed for %s: %s", clone_id, e)

    return (
        await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .where(DataSource.id == clone_id)
        )
    ).scalars().first()


# --- Device-code sign-in (MFA-safe, no app registration) --------------------
# For Microsoft connectors a member proves identity via the OAuth device-code
# flow instead of typing a password: we show a short code + verification URL,
# they approve on any device (MFA happens there), and we poll until a
# refresh_token comes back — then auto-register their private clone with it.

# Device-code scope per connector type (all share the FOCI public client).
_DEVICE_CODE_SCOPE = {
    "ms_fabric": "SCOPE_FABRIC",
    "ms_fabric_user": "SCOPE_FABRIC",
    "powerbi": "SCOPE_POWERBI",
    "powerbi_user": "SCOPE_POWERBI",
    "sharepoint": "SCOPE_GRAPH",
    "onedrive": "SCOPE_GRAPH",
}


async def _template_tenant_and_scope(db, *, template_id: str, organization: Organization):
    """Load a template and derive (tenant_id, scope_const_name, conn_type) for
    the device-code flow. Raises 404 if not a valid template."""
    org_id = str(organization.id)
    template = (
        await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .where(
                DataSource.id == str(template_id),
                DataSource.organization_id == org_id,
            )
        )
    ).scalars().first()
    if not template or not template.is_user_template or not template.connections:
        raise HTTPException(status_code=404, detail="Connector template not found")
    conn = template.connections[0]
    conn_type = conn.type
    scope_name = _DEVICE_CODE_SCOPE.get(conn_type)
    if not scope_name:
        raise HTTPException(
            status_code=400,
            detail=f"Device-code sign-in is not supported for '{conn_type}'",
        )
    cfg = conn.config
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    cfg = dict(cfg or {})
    # tenant_id may live on config or on the stored (admin) credentials; fall
    # back to the multi-tenant "organizations" endpoint (works for FOCI).
    tenant_id = cfg.get("tenant_id")
    if not tenant_id:
        try:
            saved = conn.decrypt_credentials() or {}
            tenant_id = saved.get("tenant_id")
        except Exception:
            tenant_id = None
    return (tenant_id or "organizations"), scope_name, conn_type


async def device_code_start(db, *, template_id: str, organization: Organization) -> dict:
    """Begin device-code sign-in for a template. Returns user_code + URL to show."""
    if not flags.PER_USER_CONNECTOR:
        raise HTTPException(status_code=404, detail="Per-user connector is not enabled")
    tenant_id, scope_name, _ = await _template_tenant_and_scope(
        db, template_id=template_id, organization=organization
    )
    from app.services import powerbi_device_code as dc
    scope = getattr(dc, scope_name)
    res = await asyncio.to_thread(dc.start_device_code, tenant_id, scope=scope)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "Could not start sign-in"))
    # Do NOT leak the tenant back; the poll route re-derives it from the template.
    return {
        "user_code": res.get("user_code"),
        "verification_uri": res.get("verification_uri"),
        "device_code": res.get("device_code"),
        "expires_in": res.get("expires_in"),
        "interval": res.get("interval"),
        "message": res.get("message"),
    }


async def _register_clone_fresh_session(
    *, template_id: str, org_id: str, user_id: str, credentials: dict,
    ms_identity: Optional[dict] = None,
) -> str | None:
    """Build the private clone in a BRAND-NEW db session with freshly-loaded org +
    user. The request session that served /connect is fragile here — by the time
    we reach create_connection its `organization` is expired, and accessing
    `organization.id` fires a SYNC lazy-load outside the async greenlet →
    MissingGreenlet. A fresh session + fresh rows sidesteps it entirely (same
    greenlet-safe pattern as sync_clone_bg / autolearn_clone). Returns clone id."""
    from app.dependencies import async_session_maker
    async with async_session_maker() as fresh:
        org = (
            await fresh.execute(select(Organization).where(Organization.id == str(org_id)))
        ).scalars().first()
        user = (
            await fresh.execute(select(User).where(User.id == str(user_id)))
        ).scalars().first()
        if not org or not user:
            return None
        # create_connection reads ONLY organization.id / current_user.id (pure PK
        # scalars). Force-load those + user.email, then DETACH both objects: a
        # detached, fully-populated instance returns cached attribute values and
        # never fires a session lazy-load, so the sync `organization.id` access
        # deep inside create_connection can't trigger a MissingGreenlet reload.
        _ = (org.id, user.id, user.email)
        fresh.expunge(org)
        fresh.expunge(user)
        clone = await register_template_for_user(
            fresh,
            template_id=template_id,
            organization=org,
            user=user,
            auth_mode="device_code",
            credentials=credentials,
            defer_sync=True,
            ms_identity=ms_identity,
        )
        return str(clone.id) if clone else None


async def device_code_poll(
    db, *, template_id: str, organization: Organization, user: User, device_code: str
) -> dict:
    """Poll once. On success, auto-register the caller's private clone with the
    returned refresh_token and return the created data source id."""
    if not flags.PER_USER_CONNECTOR:
        raise HTTPException(status_code=404, detail="Per-user connector is not enabled")
    tenant_id, _, _ = await _template_tenant_and_scope(
        db, template_id=template_id, organization=organization
    )
    from app.services import powerbi_device_code as dc
    res = await asyncio.to_thread(dc.poll_device_code, tenant_id, device_code)
    status = res.get("status")
    if status == "pending":
        return {"status": "pending", "slow_down": bool(res.get("slow_down"))}
    if status != "success":
        return {"status": "error", "error": res.get("error", "Sign-in failed")}

    refresh_token = res.get("refresh_token")
    if not refresh_token:
        return {"status": "error", "error": "No refresh token returned — offline_access scope missing"}

    creds = {"refresh_token": refresh_token}
    if tenant_id and tenant_id != "organizations":
        creds["tenant_id"] = tenant_id
    # Capture the signed-in MS identity from the token's id_token (flag-gated, fail-soft).
    ms_identity = _ms_identity_from_token(res)
    clone_id = await _register_clone_fresh_session(
        template_id=template_id, org_id=str(organization.id), user_id=str(user.id),
        credentials=creds, ms_identity=ms_identity,
    )
    out = {"status": "success", "data_source_id": clone_id}
    if ms_identity.get("ms_account_email"):
        out["ms_account_email"] = ms_identity["ms_account_email"]
    return out


async def connect(
    db, *, template_id: str, organization: Organization, user: User, email: str, password: str
) -> dict:
    """Adaptive sign-in: try ROPC (email+password) first. If the account has no
    MFA we connect immediately; if Microsoft demands MFA / conditional access /
    blocks legacy auth we auto-start the device-code flow and tell the caller to
    poll `/device-code/poll`. Both paths end at the SAME refresh_token→clone build."""
    if not flags.PER_USER_CONNECTOR:
        raise HTTPException(status_code=404, detail="Per-user connector is not enabled")
    if not flags.ADAPTIVE_CONNECT:
        raise HTTPException(status_code=404, detail="Adaptive connect is not enabled")
    tenant_id, scope_name, _ = await _template_tenant_and_scope(
        db, template_id=template_id, organization=organization
    )
    from app.services import powerbi_device_code as dc
    scope = getattr(dc, scope_name)
    # ropc_token uses blocking `requests` — run it off the event loop so it can't
    # poison the asyncpg greenlet context (else the next DB op in
    # register_template_for_user throws MissingGreenlet).
    res = await asyncio.to_thread(dc.ropc_token, tenant_id, email, password, scope)

    # No MFA — ROPC gave us a refresh_token. Build the private clone now (identical
    # credentials shape + auth_mode as the device-code path).
    if res.get("refresh_token"):
        creds = {"refresh_token": res["refresh_token"]}
        if tenant_id and tenant_id != "organizations":
            creds["tenant_id"] = tenant_id
        # Capture the signed-in MS identity from the token's id_token (flag-gated, fail-soft).
        ms_identity = _ms_identity_from_token(res)
        # Guarantee the ACCOUNT email is present even if the id_token omitted it, so
        # the clone is named + matched by the account the user actually typed.
        if not ms_identity.get("ms_account_email"):
            ms_identity["ms_account_email"] = (email or "").strip()
        clone_id = await _register_clone_fresh_session(
            template_id=template_id, org_id=str(organization.id), user_id=str(user.id),
            credentials=creds, ms_identity=ms_identity,
        )
        out = {"status": "connected", "data_source_id": clone_id}
        if ms_identity.get("ms_account_email"):
            out["ms_account_email"] = ms_identity["ms_account_email"]
        return out

    # MFA / conditional access / legacy blocked — fall back to device-code.
    if res.get("mfa"):
        start = await asyncio.to_thread(dc.start_device_code, tenant_id, scope=scope)
        if not start.get("ok"):
            return {"status": "error", "error": start.get("error", "Could not start device sign-in")}
        return {
            "status": "mfa_required",
            "device_code": start.get("device_code"),
            "user_code": start.get("user_code"),
            "verification_uri": start.get("verification_uri"),
            "interval": start.get("interval") or 5,
            "message": start.get("message"),
        }

    # Bad password / unknown user / other — a real failure, not an MFA fallback.
    return {"status": "error", "error": res.get("error", "Sign-in failed")}


async def autolearn_clone(clone_id: str, org_id: str, user_id: str) -> None:
    """Background task: generate description + conversation starters + a primary
    overview instruction for a freshly-created connector clone — identical to the
    manual wizard's "Use LLM to learn agent". Runs in its own DB session (the
    request session is already closed by the time this fires) and is fully
    fail-soft: the agent works without it; the user can re-learn from the UI."""
    from app.dependencies import async_session_maker
    try:
        async with async_session_maker() as db:
            org = (
                await db.execute(select(Organization).where(Organization.id == str(org_id)))
            ).scalars().first()
            if not org:
                return
            user = (
                await db.execute(select(User).where(User.id == str(user_id)))
            ).scalars().first()
            from app.services.data_source_service import DataSourceService
            # llm_sync respects the clone's use_llm_sync flag (now True) and fills
            # description / conversation_starters / primary_instruction draft.
            await DataSourceService().llm_sync(db, str(clone_id), org, user)
    except Exception as e:
        logger.warning("per_user_connector: autolearn failed for %s: %s", clone_id, e)


async def sync_clone_bg(clone_id: str, org_id: str, user_id: str,
                        learn: bool = True, trigger: str = "manual") -> None:
    """Background worker: sync a freshly-created connector clone under the user's
    own credentials and write a live, per-table sync log to the DATABASE
    (connector_sync) so the frontend can poll a CLI-style terminal — cross-worker
    safe (uvicorn --workers 4). Fully fail-soft: never raises. Runs in its own DB
    session (the request session is closed by the time this fires); ids captured as
    strings so nothing greenlet-detaches.

    Steps: connect → refresh_schema → per-table seed log → learn (llm_sync) → done.
    """
    from app.dependencies import async_session_maker
    from app.services import connector_sync
    # Hoist DataSourceService to the top of the function. It is used both in the
    # learn-from-data step (construct_client) and the llm_sync step; a later
    # function-local `from ... import DataSourceService` made Python treat the name
    # as local for the WHOLE function, so the earlier use raised UnboundLocalError,
    # which then cascaded (rollback → MissingGreenlet in llm_sync) → empty agent.
    from app.services.data_source_service import DataSourceService

    clone_id = str(clone_id)
    org_id = str(org_id)
    user_id = str(user_id)
    try:
        async with async_session_maker() as db:
            await connector_sync.start_run(
                db, data_source_id=clone_id, organization_id=org_id
            )
            await connector_sync.log_step(
                db, clone_id, level="step", phase="connecting", msg="signed in"
            )

            # Reload clone (+connections), org, user by PK.
            clone = (
                await db.execute(
                    select(DataSource)
                    .options(selectinload(DataSource.connections))
                    .where(DataSource.id == clone_id)
                )
            ).scalars().first()
            org = (
                await db.execute(select(Organization).where(Organization.id == org_id))
            ).scalars().first()
            user = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalars().first()
            if not clone or not clone.connections:
                await connector_sync.finish_run(
                    db, clone_id, phase="error", error="clone or connection not found"
                )
                await connector_sync.log_step(
                    db, clone_id, level="error", phase="error",
                    msg="clone or connection not found",
                )
                return
            conn = clone.connections[0]

            # Snapshot the active-table set BEFORE re-discovery + whether a primary
            # instruction already exists — used after seeding to diff and skip
            # re-training when nothing changed (cost guard for manual "Sync now"
            # and scheduled auto-sync alike).
            from app.models.datasource_table import DataSourceTable as _DST0
            _before_tables = set(
                (await db.execute(
                    select(_DST0.name).where(_DST0.datasource_id == clone_id)
                )).scalars().all()
            )
            _had_primary = bool(getattr(clone, "primary_instruction_id", None))

            # 3. Discover tables under the user's own credentials.
            await connector_sync.log_step(
                db, clone_id, level="step", phase="syncing",
                msg="discovering tables…",
            )
            from app.services.connection_service import ConnectionService
            await ConnectionService().refresh_schema(db, conn, current_user=user)

            # 4. Read the freshly-synced catalog (ConnectionTable rows the seed
            #    reads) → totals + per-table log lines, then seed DataSourceTable.
            from app.models.connection_table import ConnectionTable
            conn_tables = (
                await db.execute(
                    select(ConnectionTable).where(
                        ConnectionTable.connection_id == str(conn.id)
                    )
                )
            ).scalars().all()
            # De-dupe by full table identifier BEFORE totals + loop so tables_done
            # can never overshoot tables_total (duplicate / nested catalog rows →
            # otherwise "26/18"). Keep the FIRST row per distinct name.
            distinct_tables = []
            _seen = set()
            for ct in conn_tables:
                key = ct.name
                if key in _seen:
                    continue
                _seen.add(key)
                distinct_tables.append(ct)
            tables_total = len(distinct_tables)
            await connector_sync.set_totals(
                db, clone_id, tables_total=tables_total
            )
            for ct in distinct_tables:
                # ConnectionTable carries no_rows (best-effort; 0 when unavailable,
                # e.g. Power BI / on-prem catalogs that don't report row counts).
                await connector_sync.log_step(
                    db, clone_id, level="ok", table=ct.name,
                    inc_tables=True, add_rows=int(ct.no_rows or 0), msg="synced",
                )

            # Seed DataSourceTable from the catalog (reload clone fresh first).
            fresh = (
                await db.execute(
                    select(DataSource)
                    .options(selectinload(DataSource.connections))
                    .where(DataSource.id == clone_id)
                )
            ).scalars().first()
            if fresh and fresh.connections:
                await DataSourceService_seed(db, fresh, fresh.connections[0])

            # 4b. Relevance: classify each seeded table and deactivate noise
            #     (Power BI usage-metrics telemetry, staging copies, measure/empty
            #     holders) so the schema + Key Tables + starters carry only
            #     business-useful tables. Flag-gated (AUTO_TABLE_RELEVANCE, default
            #     OFF). Runs BEFORE llm_sync so the LLM never sees the noise. Fully
            #     fail-soft: a failure just leaves every table active (today's path).
            try:
                from app.settings.hybrid_flags import flags as _rflags
                _relevance_on = bool(_rflags.AUTO_TABLE_RELEVANCE)
            except Exception:
                _relevance_on = False
            if _relevance_on:
                try:
                    from app.services.table_relevance import classify_table
                    from app.models.datasource_table import DataSourceTable
                    dst_rows = (
                        await db.execute(
                            select(DataSourceTable).where(
                                DataSourceTable.datasource_id == clone_id
                            )
                        )
                    ).scalars().all()
                    n_off = 0
                    n_on = 0
                    for t in dst_rows:
                        c = classify_table(t.name, t.columns)
                        meta = dict(t.metadata_json or {})
                        # Respect a prior manual override: never re-hide a table the
                        # user explicitly re-activated in the Tables tab.
                        if meta.get("manual_active") is True:
                            meta["classification"] = c
                            t.metadata_json = meta
                            db.add(t)
                            continue
                        meta["classification"] = c
                        t.metadata_json = meta
                        # Classifier is AUTHORITATIVE: activate useful tables AND
                        # deactivate noise. (Previously it only deactivated — so if the
                        # seed left a table inactive, a useful table stayed off and the
                        # agent ended up with 0 active tables.) Manual override handled
                        # above (manual_active rows never touched here).
                        want_active = bool(c["useful"])
                        if bool(t.is_active) != want_active:
                            t.is_active = want_active
                            if want_active:
                                n_on += 1
                            else:
                                n_off += 1
                        db.add(t)
                    await db.commit()
                    if n_off or n_on:
                        await connector_sync.log_step(
                            db, clone_id, level="ok", phase="syncing",
                            msg=f"relevance: {n_on} business tables kept, "
                                f"{n_off} noise deactivated (telemetry/staging/meta)",
                        )
                except Exception as re:
                    logger.warning(
                        "per_user_connector.sync_clone_bg: relevance classify "
                        "failed for %s: %s", clone_id, re,
                    )
                    try:
                        await db.rollback()
                    except Exception:
                        pass

            # 4b-2. Learn-from-data: sample a few REAL rows per active table and
            #     record example column values into the schema the LLM reads. This
            #     grounds the generated description / starters / instruction in
            #     actual data (not just table names + the connector display name),
            #     killing domain hallucination on FK-less sources (Power BI). Runs
            #     AFTER relevance (only samples business-useful active tables) and
            #     BEFORE llm_sync. Flag-gated (LEARN_FROM_DATA, default OFF),
            #     PII-safe, fully fail-soft. Power BI only today.
            try:
                from app.settings.hybrid_flags import flags as _lflags
                _learn_data_on = bool(_lflags.LEARN_FROM_DATA)
            except Exception:
                _learn_data_on = False
            if _learn_data_on:
                try:
                    from app.services.connector_sampler import sample_active_tables
                    fresh2 = (
                        await db.execute(
                            select(DataSource)
                            .options(selectinload(DataSource.connections))
                            .where(DataSource.id == clone_id)
                        )
                    ).scalars().first()
                    if fresh2 and fresh2.connections:
                        _s_conn = fresh2.connections[0]
                        _client = await DataSourceService().construct_client(
                            db, fresh2, _s_conn
                        )
                        _n = await sample_active_tables(
                            db, _client, fresh2, conn_type=getattr(_s_conn, "type", ""),
                        )
                        if _n:
                            await connector_sync.log_step(
                                db, clone_id, level="ok", phase="syncing",
                                msg=f"learned from data: sampled real values from "
                                    f"{_n} tables",
                            )
                except Exception as se:
                    logger.warning(
                        "per_user_connector.sync_clone_bg: learn-from-data sample "
                        "failed for %s: %s", clone_id, se,
                    )
                    try:
                        await db.rollback()
                    except Exception:
                        pass

            # 4c. Schema diff + re-train decision. Re-learning is the expensive
            #     part (LLM calls), so on a re-sync we only re-train when the table
            #     set actually changed OR there is no primary instruction yet. This
            #     keeps repeated / scheduled syncs cheap ("up to date, nothing
            #     changed") while still picking up newly-granted reports/datasets.
            _after_tables = set(
                (await db.execute(
                    select(_DST0.name).where(_DST0.datasource_id == clone_id)
                )).scalars().all()
            )
            _added = sorted(_after_tables - _before_tables)
            _removed = sorted(_before_tables - _after_tables)
            _schema_changed = bool(_added or _removed)
            _first_run = not _before_tables
            if _added or _removed:
                await connector_sync.log_step(
                    db, clone_id, level="ok", phase="syncing",
                    msg=f"schema diff: +{len(_added)} new / -{len(_removed)} removed table(s)",
                )
            elif not _first_run:
                await connector_sync.log_step(
                    db, clone_id, level="ok", phase="syncing",
                    msg="schema unchanged since last sync",
                )
            # Re-train when: caller asked to learn AND (schema changed, or this is
            # the first run, or there is no primary instruction to serve yet).
            _should_learn = bool(learn) and (_schema_changed or _first_run or not _had_primary)
            if learn and not _should_learn:
                await connector_sync.log_step(
                    db, clone_id, level="ok", phase="learning",
                    msg="no schema change — skipped re-training (agent already current)",
                )

            # 5. Learn: description + conversation starters + overview instruction
            #    (same work as autolearn_clone), gated on the clone's use_llm_sync.
            #    llm_sync is one black-box LLM call, so we log real inputs BEFORE it
            #    and real results AFTER it (no faked intermediate telemetry), then
            #    promote the drafted overview instruction to the agent's PRIMARY.
            # Honest empty-state (flag CONNECTOR_JOURNEY_V2): if discovery found NO
            # queryable tables, do NOT run llm_sync — with zero real tables the LLM
            # invents a fictional schema (e.g. a fake "@SignIns" overview). Instead
            # log the truth so the agent shows "no queryable data" not a hallucination.
            try:
                from app.settings.hybrid_flags import flags as _jflags
                _journey_v2 = bool(_jflags.CONNECTOR_JOURNEY_V2)
            except Exception:
                _journey_v2 = False
            if _journey_v2 and tables_total == 0:
                await connector_sync.log_step(
                    db, clone_id, level="warn", phase="learning",
                    msg="no queryable Power BI datasets for this account "
                        "(view-only access or nothing shared) — skipping learn",
                )
            try:
                if (_should_learn
                        and getattr(fresh or clone, "use_llm_sync", False) and org is not None
                        and not (_journey_v2 and tables_total == 0)):
                    await connector_sync.log_step(
                        db, clone_id, level="step", phase="learning",
                        msg=f"reading {tables_total} tables + columns",
                    )
                    await connector_sync.log_step(
                        db, clone_id, level="step", phase="learning",
                        msg="analyzing joins & relationships",
                    )
                    from app.services.data_source_service import DataSourceService
                    learn = await DataSourceService().llm_sync(db, clone_id, org, user)
                    learn = learn or {}

                    # Real results from llm_sync's return.
                    if learn.get("summary") or learn.get("description"):
                        await connector_sync.log_step(
                            db, clone_id, level="ok", phase="learning",
                            msg="wrote agent description",
                        )
                    starters = learn.get("conversation_starters") or []
                    n_starters = len(starters) if isinstance(starters, (list, tuple)) else 0
                    if n_starters:
                        await connector_sync.log_step(
                            db, clone_id, level="ok", phase="learning",
                            msg=f"drafted {n_starters} conversation starters",
                        )
                    onboarding = learn.get("onboarding_instruction") or {}
                    instr_id = onboarding.get("id") if isinstance(onboarding, dict) else None
                    if instr_id:
                        await connector_sync.log_step(
                            db, clone_id, level="ok", phase="learning",
                            msg="built overview instruction",
                        )

                    # PHASE 1: promote the drafted overview instruction to PRIMARY so
                    # the agent Overview stops showing "No primary instruction". Point
                    # primary at the newest instruction + publish it. Fail-soft: if
                    # this fails the description/starters still landed.
                    if instr_id:
                        try:
                            from app.models.instruction import Instruction
                            instr = (
                                await db.execute(
                                    select(Instruction).where(Instruction.id == str(instr_id))
                                )
                            ).scalars().first()
                            ds_row = (
                                await db.execute(
                                    select(DataSource).where(DataSource.id == clone_id)
                                )
                            ).scalars().first()
                            if instr is not None and ds_row is not None:
                                instr.status = "published"
                                ds_row.primary_instruction_id = str(instr_id)
                                db.add(instr)
                                db.add(ds_row)
                                await db.commit()
                                await connector_sync.log_step(
                                    db, clone_id, level="ok", phase="learning",
                                    msg="published — set as primary instruction",
                                )
                        except Exception as pe:
                            logger.warning(
                                "per_user_connector.sync_clone_bg: promote primary "
                                "instruction failed for %s: %s", clone_id, pe,
                            )
                            try:
                                await db.rollback()
                            except Exception:
                                pass
            except Exception as e:
                logger.warning(
                    "per_user_connector.sync_clone_bg: llm_sync failed for %s: %s",
                    clone_id, e,
                )

            # 6. Done.
            await connector_sync.finish_run(db, clone_id, phase="done")
            await connector_sync.log_step(
                db, clone_id, level="ok", phase="done", msg="agent ready"
            )
            # Bust the cached agent Overview + headline so the next open reflects
            # the fresh sync (new tables / measures).
            try:
                from app.routes.data_source import invalidate_overview_cache
                invalidate_overview_cache(str(clone_id))
            except Exception:
                pass
            try:
                from app.services.connector_warm import invalidate_headline
                invalidate_headline(str(clone_id))
            except Exception:
                pass
    except Exception as e:
        logger.warning("per_user_connector.sync_clone_bg failed for %s: %s", clone_id, e)
        try:
            async with async_session_maker() as db2:
                await connector_sync.finish_run(
                    db2, clone_id, phase="error", error=str(e)
                )
                await connector_sync.log_step(
                    db2, clone_id, level="error", phase="error", msg=str(e)
                )
        except Exception:
            pass


async def DataSourceService_seed(db, data_source: DataSource, connection: Connection) -> None:
    """Seed DataSourceTable rows from a connection's ConnectionTable catalog."""
    from app.services.data_source_service import DataSourceService
    svc = DataSourceService()
    # Auto-activate ALL synced tables so the private clone is chat-ready the
    # instant sign-in completes — no manual Select-Tables step. The user only
    # ever sees the tables their OWN account could read, so activating all of
    # them is correct (the sign-in already scoped the catalog). max_auto_select
    # activates every table when total <= the limit, so pass a high ceiling.
    await svc.sync_domain_tables_from_connection(
        db, data_source, connection, max_auto_select=100000
    )
    await db.commit()
