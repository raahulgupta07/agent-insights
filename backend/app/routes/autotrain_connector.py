"""Autotrain HTTP surface for LIVE connector tables (P7).

POST /api/autotrain/from-connector : take EXISTING data-source tables (live
remote-DB tables read via the connector client) and auto-propose PENDING
knowledge (semantic + metrics + verified Q&A) for them — the same auto
training uploaded files get, but for connected DBs. Flag-gated
(HYBRID_AUTOTRAIN), approval-only (everything lands pending). No staging,
no register: the tables are already queryable by the agent.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.data_source import DataSource
from app.models.connection_table import ConnectionTable
from app.models.datasource_table import DataSourceTable
from app.models.llm_model import LLMModel
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autotrain", tags=["autotrain"])

_STAGING_CONN_NAME = "City Agent Staging"


class FromConnectorRequest(BaseModel):
    data_source_id: str
    table: str | None = None
    max_tables: int = 10


def _columns_for_table(row: DataSourceTable) -> list:
    """Resolve [{name, dtype}] for a DataSourceTable.

    Prefer the linked ConnectionTable schema (new architecture); fall back to
    the legacy columns JSON on the DataSourceTable itself.
    """
    cols = []
    try:
        ct = getattr(row, "connection_table", None)
        if ct is not None and ct.columns:
            cols = ct.columns
        elif row.columns:
            cols = row.columns
    except Exception:
        cols = row.columns or []
    out = []
    for c in cols or []:
        try:
            if isinstance(c, dict) and c.get("name"):
                out.append({"name": c["name"], "dtype": c.get("dtype") or "unknown"})
        except Exception:
            continue
    return out


def _connection_is_staging(row: DataSourceTable) -> bool:
    """True if this table's ConnectionTable belongs to the 'City Agent Staging'
    connection (skip those — they are the upload-staging lane, not a live DB)."""
    try:
        ct = getattr(row, "connection_table", None)
        if ct is None:
            return False
        conn = getattr(ct, "connection", None)
        return bool(conn) and (getattr(conn, "name", "") or "") == _STAGING_CONN_NAME
    except Exception:
        return False


@router.post("/from-connector")
async def autotrain_from_connector(
    body: FromConnectorRequest,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    from app.settings.hybrid_flags import flags

    if not flags.AUTOTRAIN:
        raise HTTPException(
            status_code=403, detail="autotrain is disabled (HYBRID_AUTOTRAIN off)"
        )

    ds = (
        await db.execute(
            select(DataSource).where(
                DataSource.id == body.data_source_id,
                DataSource.organization_id == organization.id,
            )
        )
    ).scalars().first()
    if ds is None:
        raise HTTPException(status_code=404, detail="data_source not found")

    # Resolve the DATA-AGENT training model: org default_data_train_model_id ->
    # default_train_model_id (shared) -> is_default fallback. Lets Settings > LLM
    # drive which model trains data agents (separate from studio training).
    model = None
    try:
        from app.services.organization_settings_service import OrganizationSettingsService
        _settings = await OrganizationSettingsService().get_settings(db, organization, user)
        _cfg = _settings.config if isinstance(_settings.config, dict) else {}
        _want = _cfg.get("default_data_train_model_id") or _cfg.get("default_train_model_id")
        if _want:
            model = (
                await db.execute(select(LLMModel).where(LLMModel.model_id == _want))
            ).scalars().first()
    except Exception:
        model = None
    if model is None:
        model = (
            await db.execute(select(LLMModel).where(LLMModel.is_default == True))  # noqa: E712
        ).scalars().first()

    # Build the (table, columns) work list.
    rows = (
        await db.execute(
            select(DataSourceTable)
            .where(
                DataSourceTable.datasource_id == ds.id,
                DataSourceTable.is_active == True,  # noqa: E712
                DataSourceTable.deleted_at.is_(None),
            )
            .options(
                selectinload(DataSourceTable.connection_table).selectinload(
                    ConnectionTable.connection
                )
            )
        )
    ).scalars().all()

    by_name = {r.name: r for r in rows}

    if body.table:
        r = by_name.get(body.table)
        if r is None:
            raise HTTPException(
                status_code=404, detail=f"table '{body.table}' not found on data source"
            )
        worklist = [r]
    else:
        cap = max(1, min(int(body.max_tables or 10), 100))
        worklist = [r for r in rows if not _connection_is_staging(r)][:cap]

    from app.services.autotrain import connector as connector_svc

    results = []
    for r in worklist:
        if _connection_is_staging(r):
            results.append({"table": r.name, "skipped": "staging connection"})
            continue
        cols = _columns_for_table(r)
        try:
            summary = await connector_svc.autotrain_connector(
                db,
                organization=organization,
                data_source=ds,
                table=r.name,
                columns=cols,
                model=model,
            )
        except Exception:  # never raises, but belt-and-suspenders
            logger.exception("autotrain_connector failed for %s", r.name)
            summary = {"table": r.name, "semantics": [], "metrics": [], "qa": 0, "errors": ["exception"]}
        results.append(summary)

    return {
        "ok": True,
        "tables": len(results),
        "results": results,
        "note": "knowledge proposed as PENDING -> approve in Knowledge > Review",
    }
