"""NEWPIPE P2/P3 — robust dlt ingest + idempotent merge (in-product graft).

Proven offline in scratchpad/p2run; ported here. Flag-gated by ``flags.DLT_INGEST``:
when OFF this module is never called and the legacy pandas path is byte-identical.

What it does (additive, durable):
- reads an uploaded CSV/XLSX with a robust reader (all-str, tolerate bad lines),
- derives ``_source_period`` from the filename (``(Jun'25)`` -> ``2025-06``),
- computes a content-hash row key so re-ingesting the same file NEVER stacks dupes,
- merges into a per-org **file-backed** DuckDB warehouse (survives restart),
- snapshots to Hive-partitioned Parquet for boot-rehydrate.

It writes under the durable uploads volume (``/app/backend/uploads/warehouse``), so
nothing is lost on container restart. Fail-soft: never raises into the request path.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# durable root on the uploads volume (cityagentanalytics_ca_uploads)
WAREHOUSE_ROOT = os.environ.get(
    "DLT_WAREHOUSE_ROOT", "/app/backend/uploads/warehouse"
)

_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def period_from_name(filename: str) -> str:
    """``MM Conso Data Report (Jun'25).csv`` -> ``2025-06``; else ``unknown``."""
    m = re.search(r"\(([A-Za-z]{3})'?(\d{2,4})\)", filename or "")
    if not m:
        return "unknown"
    mon = _MONTHS.get(m.group(1).lower(), "00")
    yy = m.group(2)
    year = yy if len(yy) == 4 else f"20{yy}"
    return f"{year}-{mon}"


def _row_key(values, period: str) -> str:
    h = hashlib.sha256(("|".join(map(str, values)) + "|" + period).encode()).hexdigest()
    return h[:32]


def _read_frame(path: str):
    """Robust reader: all-str, no NaN coercion, tolerate bad lines. CSV + XLSX."""
    import pandas as pd

    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str, keep_default_na=False)
    return pd.read_csv(
        path, dtype=str, keep_default_na=False,
        on_bad_lines="warn", encoding="utf-8-sig",
    )


def ingest_file(
    *,
    org_id: str,
    table: str,
    file_path: str,
    file_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge one file into the org's durable DuckDB warehouse + Parquet.

    Returns ``{ok, rows_total, rows_added, period, table, db, error}``. Never raises.
    """
    out: Dict[str, Any] = {
        "ok": False, "rows_total": 0, "rows_added": 0,
        "period": None, "table": table, "db": None, "error": None,
    }
    try:
        import duckdb  # local imports keep module import-safe when flag OFF
        import dlt
        import pandas as pd  # noqa: F401

        fname = file_name or os.path.basename(file_path)
        period = period_from_name(fname)
        out["period"] = period

        org_dir = os.path.join(WAREHOUSE_ROOT, str(org_id))
        os.makedirs(org_dir, exist_ok=True)
        db_path = os.path.join(org_dir, "warehouse.duckdb")
        out["db"] = db_path

        df = _read_frame(file_path)
        cols = list(df.columns)

        @dlt.resource(name=table, write_disposition="merge", primary_key="_row_key")
        def _rows():
            for rec in df.itertuples(index=False, name=None):
                yield {
                    **{cols[i]: rec[i] for i in range(len(cols))},
                    "_source_period": period,
                    "_source_file": fname,
                    "_row_key": _row_key(rec, period),
                }

        before = 0
        try:
            _c = duckdb.connect(db_path, read_only=True)
            before = _c.execute(f"SELECT count(*) FROM crm.{table}").fetchone()[0]
            _c.close()
        except Exception:
            before = 0

        pipe = dlt.pipeline(
            pipeline_name=f"ingest_{org_id}",
            destination=dlt.destinations.duckdb(db_path),
            dataset_name="crm",
        )
        pipe.run(_rows())

        con = duckdb.connect(db_path, read_only=True)
        total = con.execute(f"SELECT count(*) FROM crm.{table}").fetchone()[0]
        con.close()
        out["rows_total"] = int(total)
        out["rows_added"] = int(total - before)

        # snapshot to Hive-partitioned Parquet for boot-rehydrate (best-effort)
        try:
            pq = os.path.join(org_dir, f"parquet_{table}")
            con2 = duckdb.connect(db_path)
            con2.execute(
                f"COPY (SELECT * FROM crm.{table}) TO '{pq}' "
                f"(FORMAT parquet, PARTITION_BY (_source_period), OVERWRITE_OR_IGNORE)"
            )
            con2.close()
        except Exception as pe:  # noqa: BLE001
            logger.info("dlt_ingest: parquet snapshot skipped: %s", pe)

        out["ok"] = True
        logger.info(
            "dlt_ingest: org=%s table=%s period=%s total=%s (+%s)",
            org_id, table, period, total, out["rows_added"],
        )
    except Exception as e:  # noqa: BLE001 — never break the request path
        out["error"] = str(e)
        logger.warning("dlt_ingest failed: %s", e, exc_info=True)
    return out


def warehouse_counts(org_id: str, table: str) -> Dict[str, Any]:
    """Read-only: total rows + per-period breakdown from the durable DuckDB."""
    res: Dict[str, Any] = {"total": 0, "by_period": {}, "error": None}
    try:
        import duckdb
        db_path = os.path.join(WAREHOUSE_ROOT, str(org_id), "warehouse.duckdb")
        con = duckdb.connect(db_path, read_only=True)
        res["total"] = con.execute(f"SELECT count(*) FROM crm.{table}").fetchone()[0]
        res["by_period"] = dict(
            con.execute(
                f"SELECT _source_period, count(*) FROM crm.{table} GROUP BY 1 ORDER BY 1"
            ).fetchall()
        )
        con.close()
    except Exception as e:  # noqa: BLE001
        res["error"] = str(e)
    return res
