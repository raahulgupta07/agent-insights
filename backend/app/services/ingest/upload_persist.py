"""Import v2 (P4, HYBRID_PERSIST_WAREHOUSE): persist a spreadsheet upload into the
per-org Postgres staging schema.

Today a spreadsheet upload lives only in an in-memory DuckDB engine
(SpreadsheetClient) — lost on restart, no deep stats, and the cross-source
unified VIEW can never physically materialize (post_ingest[T4] keeps it logical).

When the flag is ON this module ALSO writes the upload's frames into
``staging_<orgid>`` via the existing loader (``load_dataframe_to_staging``), then
stamps each frame's ConnectionTable with ``metadata_json['schema']`` +
physical table name so ``post_ingest.run_cross_source_unify`` can build a REAL
``CREATE VIEW`` over the monthly siblings. The agent's query path is unchanged
(still DuckDB) — this is an additive durability/enrichment write.

Architectural + risky, so default OFF. Entirely fail-soft: never raises into the
ingest request; a failed persist leaves the in-memory source working as today.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

_MAX_ROWS_PER_TABLE = 500_000


async def persist_upload_to_warehouse(db, *, organization, data_source, file) -> dict:
    """Write the upload's frames to ``staging_<org>`` and stamp physical refs.

    Returns ``{"schema", "tables": [{"name","physical","rows"}]}``; never raises.
    """
    summary: dict = {"schema": None, "tables": []}
    try:
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified

        from app.data_sources.clients.spreadsheet_client import SpreadsheetClient
        from app.services.ingest.tenant_schema import ensure_org_staging, org_schema
        from app.services.ingest import loader, smart_upload
        from app.models.datasource_table import DataSourceTable
        from app.models.connection_table import ConnectionTable

        org_id = str(organization.id)

        # 1) provision the org staging schema (idempotent). Raises RuntimeError
        #    only when AUTOTRAIN_STAGING_ROLE_SECRET is unset -> caught below.
        try:
            ensure_org_staging(org_id)
        except Exception:  # noqa: BLE001
            logger.warning("upload_persist: staging not provisioned (secret unset?)", exc_info=True)
            return summary
        schema = org_schema(org_id)
        summary["schema"] = schema

        # 2) read the same frames the in-memory source uses (keyed by slug table).
        try:
            frames = SpreadsheetClient(path=file.path, file_id=str(file.id))._load_frames()
        except Exception:  # noqa: BLE001
            logger.warning("upload_persist: could not load frames", exc_info=True)
            return summary
        if not frames:
            return summary

        try:
            content_hash = smart_upload.file_content_hash(
                SpreadsheetClient(path=file.path)._resolve_path()
            )
        except Exception:  # noqa: BLE001
            content_hash = ""
        batch_id = uuid.uuid4().hex[:16]
        source_file = file.filename or file.path or "upload"

        # 3) write each frame to staging via the existing loader (replace load).
        written: dict[str, dict] = {}
        for table_name, df in frames.items():
            try:
                if df is None or len(df) == 0:
                    continue
                if len(df) > _MAX_ROWS_PER_TABLE:
                    df = df.head(_MAX_ROWS_PER_TABLE)
                # carry a period if the merge stamped one (single value per slice
                # not guaranteed -> pass None so the loader period-DELETE is skipped)
                rows = loader.load_dataframe_to_staging(
                    df, table_name, batch_id=batch_id, source_file=source_file,
                    content_hash=content_hash, period=None, load_key="replace",
                    schema=schema,
                )
                if rows > 0:
                    phys = loader.safe_table_name(table_name)
                    written[table_name] = {"physical": phys, "rows": rows}
                    summary["tables"].append({"name": table_name, "physical": phys, "rows": rows})
            except Exception:  # noqa: BLE001
                logger.warning("upload_persist: write failed for %s", table_name, exc_info=True)
                continue

        if not written:
            return summary

        # 4) stamp the matching ConnectionTable.metadata_json with the real schema
        #    + physical table so post_ingest[T4] can build a physical unified VIEW.
        try:
            dsts = (
                await db.execute(
                    select(DataSourceTable)
                    .where(DataSourceTable.datasource_id == str(data_source.id))
                )
            ).scalars().all()
            for dst in dsts:
                info = written.get(dst.name)
                if not info:
                    continue
                # mark the DataSourceTable
                md = dict(getattr(dst, "metadata_json", None) or {})
                md["warehouse"] = {"schema": schema, "table": info["physical"], "rows": info["rows"]}
                dst.metadata_json = md
                flag_modified(dst, "metadata_json")
                # mark its ConnectionTable so _physical_ref() resolves (schema +
                # "schema.table" name shape that _physical_ref expects).
                ct_id = getattr(dst, "connection_table_id", None)
                if ct_id:
                    ct = (
                        await db.execute(
                            select(ConnectionTable).where(ConnectionTable.id == ct_id)
                        )
                    ).scalar_one_or_none()
                    if ct is not None:
                        cmd = dict(getattr(ct, "metadata_json", None) or {})
                        cmd["schema"] = schema
                        ct.metadata_json = cmd
                        flag_modified(ct, "metadata_json")
                        if "." not in (ct.name or ""):
                            ct.name = f"{schema}.{info['physical']}"
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("upload_persist: physical-ref stamp failed", exc_info=True)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

        logger.info("upload_persist: persisted %d table(s) to %s", len(written), schema)
    except Exception:  # noqa: BLE001
        logger.warning("upload_persist.persist_upload_to_warehouse failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return summary
