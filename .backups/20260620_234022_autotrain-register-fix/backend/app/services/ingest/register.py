"""Ingest register: make a staging.<table> queryable by the agent.

This creates the catalog rows so the agent can SELECT the ingested table:
  managed-postgres Connection (reused per org)  ->  ConnectionTable  ->  DataSourceTable

⚠️ SECURITY DECISION (read before enabling in the live upload path):
The agent reaches a table via its data_source's CLIENT. A `postgresql` Connection
pointing at dash's OWN managed DB would, by default, let agent-generated SQL read
EVERY schema in that DB (public.users, etc.), not just `staging`. City-Dash solved
this with a dedicated Postgres role GRANTed only on analytics/staging
(analytics_engine.py notes "added in Phase 9"). DO NOT wire register() into the
auto-upload path until that restricted role exists and is used here as the
Connection's credentials. Until then this module is provided for completeness +
manual/opt-in use, gated by HYBRID_AUTOTRAIN and an explicit caller.

Knowledge proposal (codex -> pending semantic/metrics) does NOT need this — it
reads `staging` directly via the guarded analytics engine and is always safe.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

STAGING_CONNECTION_NAME = "City Agent Staging"
STAGING_ROLE_ENV = "AUTOTRAIN_STAGING_DB_USER"  # restricted role; required to enable
STAGING_PASS_ENV = "AUTOTRAIN_STAGING_DB_PASSWORD"


def _managed_url_parts() -> dict:
    """host/port/database from dash's managed DB url (sync driver)."""
    from sqlalchemy.engine import make_url

    from app.settings.database import _get_database_url

    u = make_url(_get_database_url())
    return {
        "host": u.host or "localhost",
        "port": u.port or 5432,
        "database": u.database or "dash",
        "user": u.username or "dash",
        "password": u.password or "",
    }


async def find_or_create_staging_connection(db, *, organization, current_user):
    """Reuse the org's managed-staging Connection, or create one.

    Uses a RESTRICTED role from env (STAGING_ROLE_ENV/STAGING_PASS_ENV) if set;
    otherwise raises — we refuse to point a full-privilege Connection at the app DB.
    """
    import os

    from sqlalchemy import select

    from app.models.connection import Connection

    existing = (
        await db.execute(
            select(Connection).where(
                Connection.organization_id == organization.id,
                Connection.name == STAGING_CONNECTION_NAME,
                Connection.deleted_at.is_(None),
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing

    role = os.environ.get(STAGING_ROLE_ENV)
    pwd = os.environ.get(STAGING_PASS_ENV)
    if not role or not pwd:
        raise RuntimeError(
            "register: refusing to create a staging Connection without a restricted role. "
            f"Set {STAGING_ROLE_ENV}/{STAGING_PASS_ENV} (a PG role GRANTed only on staging)."
        )

    parts = _managed_url_parts()
    host = os.environ.get("AUTOTRAIN_STAGING_DB_HOST") or parts["host"]
    port = int(os.environ.get("AUTOTRAIN_STAGING_DB_PORT") or parts["port"])
    database = os.environ.get("AUTOTRAIN_STAGING_DB_NAME") or parts["database"]

    # Construct the Connection DIRECTLY rather than via ConnectionService.create_connection.
    # create_connection kicks off a background refresh_schema that (a) discovers staging
    # tables as schema-qualified "staging.<table>", decides our bare-named ConnectionTable
    # row is "no longer in DB" and DELETES it + its DataSourceTable (clobbering register's
    # catalog rows), and (b) would index EVERY org's staging tables — a cross-tenant leak.
    # auto_reindex_enabled=False does NOT stop that initial scan. Building the row directly
    # means NO indexing ever runs against the shared staging schema.
    import json

    from app.models.connection import Connection

    config = {
        "host": host,
        "port": port,
        "database": database,
        "schema": "staging",
    }
    conn = Connection(
        name=STAGING_CONNECTION_NAME,
        type="postgresql",
        config=json.dumps(config) if isinstance(config, dict) else config,
        auth_policy="system_only",
        organization_id=organization.id,
        is_active=True,
        auto_reindex_enabled=False,
    )
    conn.encrypt_credentials({"user": role, "password": pwd})
    db.add(conn)
    await db.flush()
    return conn


async def register_table(
    db,
    *,
    organization,
    current_user,
    data_source,
    table: str,
    columns: list,
    no_rows: int = 0,
) -> Optional[str]:
    """Create ConnectionTable + DataSourceTable for `staging.<table>` and link
    the staging Connection to `data_source`. Returns DataSourceTable id or None.

    `columns` = [{name, dtype}]. Safe-fails (returns None) if the restricted role
    isn't configured (see module docstring).
    """
    try:
        from app.models.connection_table import ConnectionTable
        from app.models.datasource_table import DataSourceTable

        conn = await find_or_create_staging_connection(
            db, organization=organization, current_user=current_user
        )

        # link Connection <-> DataSource (M:N)
        try:
            if conn not in data_source.connections:
                data_source.connections.append(conn)
        except Exception:
            logger.exception("register: could not link connection to data_source")

        # Name the ConnectionTable SCHEMA-QUALIFIED so it matches the discovery
        # convention ("staging.<table>") and the agent's schema context. The
        # DataSourceTable below keeps the bare display name and links via
        # connection_table_id, so display stays clean.
        ct = ConnectionTable(
            id=str(uuid.uuid4()),
            connection_id=conn.id,
            name=f"staging.{table}",
            columns=columns or [],
            pks=[],
            fks=[],
            no_rows=no_rows,
            metadata_json={"schema": "staging", "source": "autotrain"},
        )
        db.add(ct)
        await db.flush()

        dst = DataSourceTable(
            id=str(uuid.uuid4()),
            datasource_id=data_source.id,
            connection_table_id=ct.id,
            name=table,
            is_active=True,
        )
        db.add(dst)
        await db.commit()
        await db.refresh(dst)
        return dst.id
    except Exception:
        logger.exception("register_table failed for %s", table)
        try:
            await db.rollback()
        except Exception:
            pass
        return None
