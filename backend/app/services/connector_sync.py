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

# Canonical training stages, in order. Every stage-tagged log line uses one of
# these; the frontend maps log lines → process-flow nodes. A stage that never
# appears in a completed run is shown 'skipped' (e.g. introspect on non-PBI).
STAGE_ORDER = [
    "discover",    # sync lists tables
    "introspect",  # PBI measures + relationships (skipped for non-PBI)
    "profile",     # columns / types
    "values",      # example values sampling
    "meanings",    # column definitions
    "metrics",     # model measures → saved metrics
    "queries",     # golden / proven queries
    "rules",       # grounding instructions
    "ready",       # done
]

# log-line level → stage status (latest line per stage wins).
_LEVEL_TO_STATUS = {
    "ok": "done",
    "active": "working",
    "step": "working",
    "error": "error",
    "warn": "skipped",
    "info": "working",
}


def _derive_stages(log: list, phase: str | None) -> dict:
    """Reduce the run's log[] into {stage: 'done'|'working'|'queued'|'skipped'}.

    Latest status per stage; a stage never seen is 'skipped' once the run is
    complete (phase done/error) else 'queued' (a future step). Fail-soft."""
    try:
        seen: dict = {}
        for entry in (log or []):
            st = entry.get("stage") if isinstance(entry, dict) else None
            if not st or st not in STAGE_ORDER:
                continue
            mapped = _LEVEL_TO_STATUS.get(entry.get("level"), "working")
            seen[st] = mapped
        complete = str(phase or "") in ("done", "error")
        default = "skipped" if complete else "queued"
        # Furthest-progressed stage index: anything the run has moved PAST is done,
        # even if that stage's last log line was a mid-work 'step'/'active'.
        furthest = max(
            (STAGE_ORDER.index(s) for s in seen), default=-1
        )
        out: dict = {}
        for i, s in enumerate(STAGE_ORDER):
            status = seen.get(s)
            if status is None:
                out[s] = default
            elif status == "working" and (i < furthest or complete):
                out[s] = "done"
            else:
                out[s] = status
        return out
    except Exception:  # fail-soft — omit on error
        return {}


async def _learned_counts(db, data_source_id: str) -> dict:
    """Cheap per-data-source result counts the FE lanes need. Each metric in its
    own try/except so a single failing query never drops the rest; omit on error."""
    ds_id = str(data_source_id)
    out: dict = {}
    from sqlalchemy import func, select as _select

    # tables — active, non-deleted DataSourceTable
    try:
        from app.models.datasource_table import DataSourceTable
        rows = (await db.execute(
            _select(DataSourceTable.columns).where(
                DataSourceTable.datasource_id == ds_id,
                DataSourceTable.is_active == True,  # noqa: E712
                DataSourceTable.deleted_at.is_(None),
            )
        )).all()
        out["tables"] = len(rows)
        # columns — sum of column lists across active tables
        try:
            out["columns"] = sum(len(c[0] or []) for c in rows if isinstance(c[0], (list, tuple)))
        except Exception:
            pass
        # values — active tables with at least one column carrying example 'values'
        try:
            nval = 0
            for (cols,) in rows:
                for col in (cols or []):
                    md = (col.get("metadata") or {}) if isinstance(col, dict) else {}
                    if md.get("values"):
                        nval += 1
            out["values"] = nval
        except Exception:
            pass
    except Exception:
        pass

    # definitions — approved semantic columns with a non-empty meaning
    try:
        from app.models.semantic_table import SemanticColumn, SemanticTable
        n = (await db.execute(
            _select(func.count()).select_from(SemanticColumn)
            .join(SemanticTable, SemanticColumn.semantic_table_id == SemanticTable.id)
            .where(
                SemanticTable.data_source_id == ds_id,
                SemanticColumn.status == "approved",
                func.coalesce(SemanticColumn.meaning, "") != "",
            )
        )).scalar()
        out["definitions"] = int(n or 0)
    except Exception:
        pass

    # metrics — metric_definitions for this data source
    try:
        from app.models.metric_definition import MetricDefinition
        n = (await db.execute(
            _select(func.count()).select_from(MetricDefinition)
            .where(MetricDefinition.data_source_id == ds_id)
        )).scalar()
        out["metrics"] = int(n or 0)
    except Exception:
        pass

    # rules — instructions linked to this DS via the association table
    try:
        from app.models.instruction import instruction_data_source_association as _assoc
        n = (await db.execute(
            _select(func.count()).select_from(_assoc)
            .where(_assoc.c.data_source_id == ds_id)
        )).scalar()
        out["rules"] = int(n or 0)
    except Exception:
        pass

    return out


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
    stage: str | None = None,
) -> None:
    """Append one log entry and (optionally) bump counters / set phase, then commit
    so pollers see it live. level ∈ step|ok|active|error. Optional per-table
    ``status`` (e.g. syncing|done) and ``rows`` (row count) enrich the entry for a
    table-by-table checklist; omitted → entry unchanged (backward-compat).

    Optional ``stage`` tags the line with one of the canonical training stages
    (see STAGE_ORDER) so the frontend can light up an always-visible process-flow
    strip. Default None → entry unchanged (backward-compat)."""
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
        if stage is not None:
            entry["stage"] = stage
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
        out = {
            "phase": run.phase,
            "tables_total": int(run.tables_total or 0),
            "tables_done": int(run.tables_done or 0),
            "rows": int(run.rows or 0),
            "log": run.log or [],
            "error": run.error,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        }
        # Additive + fail-soft: a compact stage summary (FE process-flow strip) and
        # result counts (FE lanes) so the FE doesn't parse every log line. Omit on
        # error — existing FE that ignores these is unaffected.
        try:
            stages = _derive_stages(run.log or [], run.phase)
            if stages:
                out["stages"] = stages
        except Exception:
            pass
        try:
            learned = await _learned_counts(db, ds_id)
            if learned:
                out["learned"] = learned
        except Exception:
            pass
        return out
    except Exception as e:  # fail-soft
        logger.warning("connector_sync.get_run failed for %s: %s", ds_id, e)
        return None
