"""Live per-clone connector sync log (DB-backed, cross-worker-safe).

Helpers that read/write a single `ConnectorSyncRun` row per per-user connector
clone so the frontend can poll a CLI-style terminal of the sync. The log lives in
the DATABASE (not memory) so it works under `uvicorn --workers 4` — any worker can
serve the poll. All helpers are FAIL-SOFT: they never raise into their callers (the
background sync worker), so a logging hiccup can never break the actual sync.

Written by services/per_user_connector.py::sync_clone_bg; read by
routes/data_source.py GET /data_sources/{id}/sync-status.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, delete

from app.models.connector_sync_run import ConnectorSyncRun

logger = logging.getLogger(__name__)

_LOG_CAP = 300


async def _get(db, data_source_id: str):
    return (
        await db.execute(
            select(ConnectorSyncRun).where(
                ConnectorSyncRun.data_source_id == str(data_source_id)
            )
        )
    ).scalars().first()


async def start_run(db, *, data_source_id, organization_id) -> ConnectorSyncRun | None:
    """Upsert the single run row for this clone → phase 'connecting', empty log."""
    ds_id = str(data_source_id)
    try:
        # Reset any prior row for this clone (one live run per clone).
        await db.execute(
            delete(ConnectorSyncRun).where(ConnectorSyncRun.data_source_id == ds_id)
        )
        run = ConnectorSyncRun(
            data_source_id=ds_id,
            organization_id=str(organization_id),
            phase="connecting",
            tables_total=0,
            tables_done=0,
            rows=0,
            log=[],
            error=None,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run
    except Exception as e:  # fail-soft
        logger.warning("connector_sync.start_run failed for %s: %s", ds_id, e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def log_step(
    db,
    data_source_id,
    *,
    level: str,
    msg: str,
    table: str | None = None,
    phase: str | None = None,
    inc_tables: bool = False,
    add_rows: int = 0,
    status: str | None = None,
    rows: int | None = None,
) -> None:
    """Append one log entry and (optionally) bump counters / set phase, then commit
    so pollers see it live. level ∈ step|ok|active|error. Optional per-table
    ``status`` (e.g. syncing|done) and ``rows`` (row count) enrich the entry for a
    table-by-table checklist; omitted → entry unchanged (backward-compat)."""
    ds_id = str(data_source_id)
    try:
        run = await _get(db, ds_id)
        if run is None:
            return
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "level": level,
            "msg": msg,
            "table": table,
        }
        if status is not None:
            entry["status"] = status
        if rows is not None:
            entry["rows"] = rows
        # Reassign a NEW list so SQLAlchemy JSON change-tracking fires.
        run.log = (run.log or [])[-(_LOG_CAP - 1):] + [entry]
        if phase is not None:
            run.phase = phase
        if inc_tables:
            run.tables_done = int(run.tables_done or 0) + 1
        if add_rows:
            run.rows = int(run.rows or 0) + int(add_rows)
        run.updated_at = datetime.utcnow()
        db.add(run)
        await db.commit()
    except Exception as e:  # fail-soft
        logger.warning("connector_sync.log_step failed for %s: %s", ds_id, e)
        try:
            await db.rollback()
        except Exception:
            pass


async def set_totals(db, data_source_id, *, tables_total: int) -> None:
    ds_id = str(data_source_id)
    try:
        run = await _get(db, ds_id)
        if run is None:
            return
        run.tables_total = int(tables_total or 0)
        run.updated_at = datetime.utcnow()
        db.add(run)
        await db.commit()
    except Exception as e:  # fail-soft
        logger.warning("connector_sync.set_totals failed for %s: %s", ds_id, e)
        try:
            await db.rollback()
        except Exception:
            pass


async def finish_run(db, data_source_id, *, phase: str = "done", error: str | None = None) -> None:
    ds_id = str(data_source_id)
    try:
        run = await _get(db, ds_id)
        if run is None:
            return
        run.phase = phase
        if error is not None:
            run.error = error
        run.updated_at = datetime.utcnow()
        db.add(run)
        await db.commit()
    except Exception as e:  # fail-soft
        logger.warning("connector_sync.finish_run failed for %s: %s", ds_id, e)
        try:
            await db.rollback()
        except Exception:
            pass


async def get_run(db, data_source_id) -> dict | None:
    """Return a lightweight dict for the poll route, or None if no run exists."""
    ds_id = str(data_source_id)
    try:
        run = await _get(db, ds_id)
        if run is None:
            return None
        return {
            "phase": run.phase,
            "tables_total": int(run.tables_total or 0),
            "tables_done": int(run.tables_done or 0),
            "rows": int(run.rows or 0),
            "log": run.log or [],
            "error": run.error,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        }
    except Exception as e:  # fail-soft
        logger.warning("connector_sync.get_run failed for %s: %s", ds_id, e)
        return None
