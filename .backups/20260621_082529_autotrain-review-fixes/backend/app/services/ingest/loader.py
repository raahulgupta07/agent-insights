"""Ingest loader: DataFrame -> staging.<table> with lineage columns.

Writes through the RAW loader write-engine (tenant_schema.loader_write_engine(),
no write-guard) so quoted/reserved identifiers work (reserved-word table names +
the hand-quoted period-DELETE path). Server-derived schema only (never agent-
reachable). Sync. Never raises — returns 0 on failure.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

STAGING_SCHEMA = "staging"
_LINEAGE = ["_source_file", "_period", "_batch_id", "_content_hash", "_row_key", "_ingested_at"]


def safe_table_name(name: str) -> str:
    """Lowercase slug, alnum+underscore only, never strips a trailing underscore
    blindly (slug convention). Falls back to 'dataset'.
    """
    s = re.sub(r"[^a-z0-9_]+", "_", (name or "").lower()).strip("_")
    if not s:
        # degenerate slug (empty / symbol-only input): append a short stable hash
        # of the original name so two different empty-slug names don't collide.
        h = hashlib.md5((name or "").encode("utf-8")).hexdigest()[:6]
        return "t_" + h
    if s[0].isdigit():
        s = "t_" + s
    return s[:60] or "dataset"


def _stamp_lineage(
    df: pd.DataFrame,
    *,
    source_file: str,
    batch_id: str,
    content_hash: str,
    period: Optional[str],
) -> pd.DataFrame:
    out = df.copy()
    out["_source_file"] = source_file
    out["_period"] = period
    out["_batch_id"] = batch_id
    out["_content_hash"] = content_hash
    out["_row_key"] = [f"{batch_id}:{i}" for i in range(len(out))]
    out["_ingested_at"] = datetime.now(timezone.utc).isoformat()
    return out


def load_dataframe_to_staging(
    df: pd.DataFrame,
    table: str,
    *,
    batch_id: str,
    source_file: str,
    content_hash: str = "",
    period: Optional[str] = None,
    load_key: str = "replace",  # "replace" | "period" | "append"
    schema: str = STAGING_SCHEMA,  # per-org schema (staging_<orgid>) or shared "staging"
    engine=None,
) -> int:
    """Load df into <schema>.<table>. Returns row count written (0 on failure).

    load_key="period": DELETE WHERE _period = period, then append (monthly drops).
    load_key="replace": drop+recreate.
    load_key="append": append.
    """
    if df is None or df.empty:
        logger.warning("loader: empty df for %s", table)
        return 0
    tbl = safe_table_name(table)
    try:
        if engine is None:
            from app.services.ingest.tenant_schema import loader_write_engine

            engine = loader_write_engine()

        stamped = _stamp_lineage(
            df, source_file=source_file, batch_id=batch_id,
            content_hash=content_hash, period=period,
        )

        from sqlalchemy import text

        if load_key == "append":
            if_exists = "append"
        elif load_key == "period" and period is not None:
            if_exists = "append"
        else:
            if_exists = "replace"

        # M3: serialize concurrent loads of the SAME (schema, table). Acquire a
        # transaction-scoped Postgres advisory lock and run the whole load inside
        # that one transaction so the period-DELETE and to_sql share it (and the
        # lock auto-releases at txn end). Both must run on the SAME `conn`.
        with engine.begin() as conn:
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                {"k": f"{schema}.{tbl}"},
            )

            if load_key == "period" and period is not None:
                # ensure table exists, then delete this period before appending
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema=:s AND table_name=:t"
                    ),
                    {"s": schema, "t": tbl},
                ).first()
                if exists:
                    conn.execute(
                        text(f'DELETE FROM "{schema}"."{tbl}" WHERE _period = :p'),
                        {"p": period},
                    )

            stamped.to_sql(
                tbl,
                conn,
                schema=schema,
                if_exists=if_exists,
                index=False,
                method="multi",
                chunksize=1000,
            )
        logger.info("loader: wrote %d rows -> %s.%s (%s)", len(stamped), schema, tbl, load_key)
        return len(stamped)
    except Exception:
        logger.exception("loader failed for %s", tbl)
        return 0
