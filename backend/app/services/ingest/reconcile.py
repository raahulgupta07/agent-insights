"""Ingest reconcile gate (Phase 2, HYBRID_INGEST_RECONCILE).

After a multi-file spreadsheet upload is materialized, compare what actually
loaded against what was expected and surface any gap — instead of a bad file
being silently swallowed (the "6 months uploaded, 1 lands, agent invents the
rest" failure).

This mirrors the chat-upload path's fail-loud behavior: chat reads the whole
file live and errors out loud on a bad read; this makes the persistent ingest
do the same after the fact.

Signals used:
- ``SpreadsheetClient.last_ingest_report`` (Phase 1) — per merged file
  outcome (loaded|failed + rows + error), produced by ``_load_frames``.
- ``DataSourceTable.no_rows`` — rows actually materialized per table.

Outcome (when the flag is on and the source is a multi-file merge):
- a ``ingest_coverage`` dict is stamped on the connection config and on each
  active table's ``metadata_json``;
- the source is marked DEGRADED when any file failed to load OR the
  materialized row count falls short of the loaded source rows.

Everything is fail-soft: any error returns None and the upload proceeds exactly
as today. Flag OFF -> this is never called (route-gated) and the source is
byte-identical to today.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.connection import Connection
from app.models.datasource_table import DataSourceTable

logger = logging.getLogger(__name__)


def _parse_config(conn: Connection) -> dict:
    try:
        return json.loads(conn.config) if isinstance(conn.config, str) else (conn.config or {})
    except Exception:  # noqa: BLE001
        return {}


def _build_coverage(report: dict, materialized_rows: int) -> dict:
    """Turn the Phase-1 per-file report + materialized row count into a coverage
    summary with a DEGRADED verdict and a human-readable reason."""
    files = report.get("files") or []
    loaded = [f for f in files if f.get("status") == "loaded"]
    failed = [f for f in files if f.get("status") == "failed"]
    source_rows = int(report.get("source_rows") or 0)

    periods_loaded = sorted({f.get("period") for f in loaded if f.get("period")})

    # DEGRADED when a file failed to parse, fewer files loaded than expected, or
    # the materialized table holds fewer rows than the files we read.
    # NB: spreadsheet/DuckDB tables often report no_rows=0 (count not populated
    # at sync time) — treat materialized_rows==0 as UNKNOWN, not a shortfall, so
    # an all-loaded merge isn't falsely flagged. The file-failure signal is
    # primary; the row cross-check only applies when we actually have a count.
    row_short = materialized_rows > 0 and materialized_rows < source_rows
    degraded = bool(failed) or (
        int(report.get("loaded_files") or 0) < int(report.get("expected_files") or 0)
    ) or row_short

    reasons = []
    if failed:
        names = ", ".join(str(f.get("label") or f.get("path")) for f in failed)
        reasons.append(f"{len(failed)} of {report.get('expected_files')} file(s) failed to load: {names}")
    if row_short:
        reasons.append(f"materialized {materialized_rows} rows vs {source_rows} read from files")

    return {
        "status": "degraded" if degraded else "ok",
        "expected_files": int(report.get("expected_files") or 0),
        "loaded_files": int(report.get("loaded_files") or 0),
        "failed_files": int(report.get("failed_files") or 0),
        "source_rows": source_rows,
        "materialized_rows": int(materialized_rows),
        "periods_loaded": periods_loaded,
        "failed": [
            {"label": f.get("label"), "period": f.get("period"),
             "path": f.get("path"), "error": f.get("error")}
            for f in failed
        ],
        "reason": "; ".join(reasons) if reasons else "all files loaded and reconciled",
    }


async def run_ingest_reconcile(
    db: AsyncSession,
    *,
    organization,
    data_source,
    connection: Connection,
) -> Optional[dict]:
    """Reconcile a just-ingested multi-file spreadsheet source. Returns the
    coverage dict (also persisted) or None when not applicable / on any error."""
    try:
        from app.settings.hybrid_flags import flags as _flags
        if not _flags.INGEST_RECONCILE:
            return None
    except Exception:  # noqa: BLE001
        return None

    try:
        cfg = _parse_config(connection)
        merged_paths = cfg.get("merged_paths") or []
        # Single-file source: no merge -> no silent-drop risk -> nothing to gate.
        if not merged_paths:
            return None

        from app.data_sources.clients.spreadsheet_client import SpreadsheetClient

        client = SpreadsheetClient(
            path=cfg.get("path"),
            sheet_names=cfg.get("sheet_names"),
            file_id=cfg.get("file_id"),
            merged_paths=merged_paths,
        )
        # Re-read to obtain the Phase-1 per-file report (cheap relative to a full
        # query; the files were just uploaded and are on local disk).
        client._load_frames()
        report = client.last_ingest_report
        if not report:
            return None

        # Materialized rows = sum of active table no_rows for this source.
        rows = (
            await db.execute(
                select(DataSourceTable).where(
                    DataSourceTable.datasource_id == data_source.id,
                    DataSourceTable.is_active.is_(True),
                )
            )
        ).scalars().all()
        materialized_rows = int(sum((t.no_rows or 0) for t in rows))

        coverage = _build_coverage(report, materialized_rows)

        # Persist: source-level marker on the connection config (queryable JSON,
        # no migration) + per-table marker on metadata_json so the agent context
        # builder (Phase 3) and the UI (Phase 5) can read it.
        cfg["ingest_coverage"] = coverage
        connection.config = json.dumps(cfg) if isinstance(connection.config, str) else cfg
        flag_modified(connection, "config")

        for t in rows:
            md = dict(t.metadata_json or {})
            md["ingest_coverage"] = coverage
            t.metadata_json = md
            flag_modified(t, "metadata_json")

        await db.commit()

        if coverage["status"] == "degraded":
            logger.warning(
                "ingest reconcile: source %s DEGRADED — %s",
                data_source.id, coverage["reason"],
            )
        else:
            logger.info(
                "ingest reconcile: source %s OK (%s files, %s rows)",
                data_source.id, coverage["loaded_files"], coverage["materialized_rows"],
            )
        return coverage
    except Exception:  # noqa: BLE001 — never block the upload on the reconcile
        logger.warning("ingest reconcile failed; proceeding", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
