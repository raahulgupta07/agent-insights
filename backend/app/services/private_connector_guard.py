"""Private (per-agent) connector guards — HYBRID_AGENT_CONNECTORS.

A connection whose ``owner_user_id`` is set is a PRIVATE, creator-only connector
bound to a single Studio (``studio_id``). Org connectors (``owner_user_id`` NULL)
behave exactly as before — every helper here short-circuits to a no-op for them,
so the NULL-owner path is byte-identical to today.

Two invariants are enforced from one place so every call-site stays consistent:

  * CREATOR-ONLY — only ``owner_user_id`` may read/edit/delete/test/reindex/list
    a private connector. There is NO admin bypass for an owned connector.
  * NON-SHAREABLE — a private connector (or a DataSource wrapping one) can never
    be shared: no ResourceGrant, no DataSourceMembership, no ``is_public=True``.

Import-safe regardless of the flag — the flag is read here so callers don't have
to. When the flag is OFF there are no owned connectors (the create endpoint 404s),
so these guards are inert.
"""
from __future__ import annotations

from typing import Iterable, Optional

from app.errors import AppError, ErrorCode
from app.settings.hybrid_flags import flags


def feature_enabled() -> bool:
    """True when per-agent private connectors are enabled."""
    return _agent_connectors_enabled()


def _agent_connectors_enabled() -> bool:
    # Resolved through the SAME per-org override layer as every other hybrid flag
    # (the @property delegates to `_bool`, which reads `_OVERRIDES` first, then
    # env, then the default). Registered in UPGRADE_FLAGS so the override loader
    # honours it.
    return bool(flags.AGENT_CONNECTORS)


def require_feature_enabled() -> None:
    """Raise 404 (feature locked) unless HYBRID_AGENT_CONNECTORS is on.

    Mirrors routes/me_groups.py `_ensure_enabled` — a locked feature is a 404,
    not a 403, so the endpoint's very existence isn't leaked.
    """
    if not _agent_connectors_enabled():
        raise AppError(
            ErrorCode.FEATURE_LOCKED,
            "Per-agent private connectors are not enabled.",
            status_code=404,
        )


def is_private(connection) -> bool:
    """A connection is PRIVATE iff it carries an owner_user_id."""
    return getattr(connection, "owner_user_id", None) is not None


def owns(connection, user) -> bool:
    """True when `user` is the creator/owner of a private connection."""
    owner = getattr(connection, "owner_user_id", None)
    if owner is None:
        return True  # org connector — ownership n/a
    return str(owner) == str(getattr(user, "id", None))


def require_owner(connection, user) -> None:
    """CREATOR-ONLY. 403 if the connection is owned and `user` isn't the owner.

    No-op for org connectors (owner_user_id NULL). No admin bypass.
    """
    if not is_private(connection):
        return
    if not owns(connection, user):
        raise AppError(
            ErrorCode.ACCESS_DENIED,
            "This is a private connector — only its creator can access it.",
            status_code=403,
        )


def deny_share(connection) -> None:
    """NON-SHAREABLE. 403 if the connection is private.

    Call at every site that could share a connector (ResourceGrant /
    DataSourceMembership / is_public=True). No-op for org connectors.
    """
    if is_private(connection):
        raise AppError(
            ErrorCode.ACCESS_DENIED,
            "A private connector cannot be shared. Recreate it as an "
            "organization connector to share.",
            status_code=403,
        )


def filter_visible(connections: Iterable, user) -> list:
    """Drop private connectors NOT owned by `user`; keep org + own-private.

    Used by the connection LIST route so a member never sees someone else's
    private connector. Org connectors (NULL owner) stay visible to everyone.
    """
    out = []
    for c in connections:
        if is_private(c) and not owns(c, user):
            continue
        out.append(c)
    return out


async def teardown_private_connection(db, connection) -> None:
    """Hard-delete a PRIVATE connection + its wrapping private DataSource(s) in
    FK-safe order.

    An INDEXED connector has rows in ``connection_tables`` (FK → connections) and
    ``datasource_tables`` (FK ``datasource_id`` → data_sources, FK
    ``connection_table_id`` → connection_tables). The Connection's ORM cascade
    on ``connection_tables`` would emit DELETEs that the lingering
    ``datasource_tables`` FK rejects — an ORDERING problem. So we explicitly
    clear the dependents first, bottom-up:

      1. StudioDataSource pins for each wrapping DS,
      2. datasource_tables for each wrapping DS (frees the connection_tables FK),
      3. the domain_connection link row(s) for this connection,
      4. the wrapping DataSource(s) (ORM delete),
      5. the connection itself (ORM cascade now clears connection_tables,
         user_credentials [Fernet], user_tables, connection_tools, user_tools,
         indexings).

    All deletes are idempotent — a NEVER-indexed connector simply has no
    connection_tables/datasource_tables rows, so steps 2 are no-ops. Core
    deletes are used for the join/link tables (no ORM model handy / to control
    ordering). Does NOT commit — the caller owns the transaction.
    ``connection.data_sources`` (and each ds.connections) must be loaded by the
    caller. No-op for org connectors (defensively guarded).
    """
    from sqlalchemy import delete as sa_delete
    from app.models.studio import StudioDataSource
    from app.models.datasource_table import DataSourceTable
    from app.models.domain_connection import domain_connection

    if not is_private(connection):
        return

    conn_id = str(connection.id)

    for ds in list(getattr(connection, "data_sources", None) or []):
        # Only tear down a DataSource that wraps THIS connection alone — a DS
        # also linked to other connections must survive.
        if len(getattr(ds, "connections", None) or []) != 1:
            continue
        ds_id = str(ds.id)

        # 1. Drop the studio pin(s) for this wrapping DS.
        await db.execute(
            sa_delete(StudioDataSource).where(StudioDataSource.agent_id == ds_id)
        )
        # 2. Drop datasource_tables for this DS — they reference BOTH this DS and
        #    the connection_tables we're about to cascade. Column is
        #    `datasource_id` (no underscore between data+source). No-op when the
        #    connector was never indexed.
        await db.execute(
            sa_delete(DataSourceTable).where(DataSourceTable.datasource_id == ds_id)
        )
        # 3. Drop the M:N link row(s) (domain_connection: data_source_id,
        #    connection_id) so the DataSource delete can't trip the secondary.
        await db.execute(
            domain_connection.delete().where(
                domain_connection.c.data_source_id == ds_id
            )
        )
        # 4. Delete the wrapping DataSource. Flush so the link-table + table
        #    deletes land before the connection cascade runs.
        await db.delete(ds)

    await db.flush()

    # 5. Delete the connection — its ORM "all, delete-orphan" cascades now clear
    #    connection_tables (no longer referenced by datasource_tables),
    #    user_credentials (Fernet), user_tables, connection_tools, user_tools,
    #    indexings.
    await db.delete(connection)


async def deny_share_data_source(db, data_source) -> None:
    """NON-SHAREABLE for a DataSource that WRAPS a private connector.

    A DataSource that is bound to a private connection inherits the
    non-shareable invariant: granting it to others would leak the owner's
    private connector. 403 when any linked connection is private.

    `data_source.connections` must already be loaded (callers eager-load it).
    """
    for conn in (getattr(data_source, "connections", None) or []):
        if is_private(conn):
            raise AppError(
                ErrorCode.ACCESS_DENIED,
                "This agent is backed by a private connector and cannot be "
                "shared with other users.",
                status_code=403,
            )
