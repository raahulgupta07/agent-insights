"""Generic ingest self-heal (flag HYBRID_INGEST_SELFHEAL).

Repairs an agent whose same-schema data got SPLIT across multiple physical
staging tables — the classic "6 monthly files uploaded in separate sessions,
only the first month's table stayed bound, the other five sit as orphan tables"
failure. It stitches the orphans back into the agent's ONE bound table.

What it does (generic, multi-tenant, safe for ANY dataset):
  1. Resolve the agent's bound/active physical table(s) from ``datasource_tables``
     and read each one's column-signature (the set of physical column names).
  2. Scan the SAME org staging schema (``staging_<orgid-slug>``) for ORPHAN
     physical tables whose column-signature MATCHES a bound table but which are
     NOT the bound table and are NOT referenced by any non-deleted
     ``datasource_tables`` row of any live data source (never steal another live
     agent's table).
  3. BACKUP first (pg_dump of the affected tables when available, else record
     row counts), then in a SINGLE transaction UNION-append the orphan rows into
     the bound table. IDEMPOTENT: rows already present are skipped — dedupe on
     ``_row_key`` (row-level) or ``_content_hash`` (file-level) when those
     lineage columns exist, else a full-row match. The partition/source columns
     (``_period`` / ``_source_period`` / ``_source_file``) are carried over from
     the orphan rows unchanged (never hardcode months).
  4. Update ``datasource_tables.no_rows`` to the new physical count.
  5. Optionally DROP the now-merged orphans — only when ``drop_orphans`` and not
     ``dry_run``, and only AFTER the merge transaction commits.

Fail-soft: never raises. On any error returns ``ok=False`` + a ``note``.

Return shape:
    {"ok": bool, "tables_stitched": int, "rows_added": int,
     "final_rows": int, "note": str, "details": [...]}
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone

from sqlalchemy import select, text

logger = logging.getLogger(__name__)

# Lineage columns the loader stamps on every staged row. Used to pick a dedupe
# key and to know which columns are "partition/source" markers to preserve.
_ROWKEY = "_row_key"
_CONTENT_HASH = "_content_hash"
_PARTITION_COLS = ("_period", "_source_period", "_source_file")


def _q(ident: str) -> str:
    """Quote a SQL identifier (column/table names can contain spaces/colons)."""
    return '"' + str(ident).replace('"', '""') + '"'


def _safe_name(name: str) -> str:
    """Physical table slug (mirrors loader.safe_table_name)."""
    try:
        from app.services.ingest.loader import safe_table_name
        return safe_table_name(name)
    except Exception:  # noqa: BLE001
        return str(name or "")


# --------------------------------------------------------------------------- #
# Sync DB worker (runs on the raw superuser loader engine, off the event loop) #
# --------------------------------------------------------------------------- #
def _columns(conn, schema: str, table: str) -> list:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=:s AND table_name=:t ORDER BY column_name"
        ),
        {"s": schema, "t": table},
    ).fetchall()
    return [r[0] for r in rows]


def _list_physical_tables(conn, schema: str) -> list:
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=:s AND table_type='BASE TABLE'"
        ),
        {"s": schema},
    ).fetchall()
    return [r[0] for r in rows]


def _count(conn, schema: str, table: str) -> int:
    try:
        return int(conn.execute(
            text(f'SELECT count(*) FROM {_q(schema)}.{_q(table)}')
        ).scalar() or 0)
    except Exception:  # noqa: BLE001
        return -1


def _dedupe_where(cols: list, bound_q: str) -> str:
    """Build the NOT EXISTS dedupe predicate. Orphan is aliased ``o`` in the
    outer query; the bound table (``bound_q`` = quoted schema.table) is aliased
    ``b`` in the sub-select."""
    if _ROWKEY in cols:
        return (f"NOT EXISTS (SELECT 1 FROM {bound_q} b "
                f"WHERE b.{_q(_ROWKEY)} = o.{_q(_ROWKEY)})")
    if _CONTENT_HASH in cols:
        return (f"NOT EXISTS (SELECT 1 FROM {bound_q} b "
                f"WHERE b.{_q(_CONTENT_HASH)} = o.{_q(_CONTENT_HASH)})")
    # full-row match (NULL-safe)
    preds = " AND ".join(
        f"b.{_q(c)} IS NOT DISTINCT FROM o.{_q(c)}" for c in cols
    )
    return f"NOT EXISTS (SELECT 1 FROM {bound_q} b WHERE {preds})"


def _pg_dump(schema: str, tables: list) -> str:
    """Best-effort pg_dump of the affected tables → a .sql file. Returns the
    path, or "" when pg_dump is unavailable / fails (we still record counts)."""
    try:
        from app.settings.database import _get_database_url
        url = _get_database_url()
        for drv in ("+asyncpg", "+psycopg2", "+psycopg"):
            url = url.replace(drv, "")
        if not url.startswith("postgresql"):
            return ""
        outdir = os.environ.get("SELFHEAL_BACKUP_DIR") or os.path.join(
            tempfile.gettempdir(), "selfheal_backups")
        os.makedirs(outdir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        path = os.path.join(outdir, f"selfheal_{schema}_{ts}.sql")
        args = ["pg_dump", url, "--no-owner", "--no-privileges"]
        for t in tables:
            args += ["-t", f"{schema}.{t}"]
        args += ["-f", path]
        subprocess.run(args, check=True, capture_output=True, timeout=300)
        return path
    except Exception:  # noqa: BLE001
        return ""


def _heal_sync(schema: str, bound_list: list, claimed: set,
               dry_run: bool, drop_orphans: bool) -> dict:
    """The physical-table work. bound_list = [{dt_id,physical,no_rows}]. claimed
    = set of physical names that belong to a live datasource_table (never touch).
    Returns a summary dict (never raises out to the async caller directly, but
    the caller also wraps this)."""
    from app.services.ingest.tenant_schema import loader_write_engine
    eng = loader_write_engine()

    out = {"tables_stitched": 0, "rows_added": 0, "details": [],
           "final_rows_by_dt": {}, "backup": None}

    # 1) discover physical tables + signatures
    with eng.connect() as conn:
        phys = _list_physical_tables(conn, schema)
        bound_sig = {}
        for b in bound_list:
            name = b["physical"]
            if name in phys:
                bound_sig[name] = (b, frozenset(_columns(conn, schema, name)))
        candidates = [t for t in phys if t not in claimed]
        cand_sig = {t: frozenset(_columns(conn, schema, t)) for t in candidates}

    if not bound_sig:
        out["note"] = "no bound physical table found in staging schema"
        return out

    # 2) assign each orphan to the FIRST bound table it matches (no double-merge)
    used: set = set()
    plan = []  # [{bound, cols, orphans:[names]}]
    for name, (b, sig) in bound_sig.items():
        orphans = [t for t in candidates
                   if t not in used and cand_sig[t] == sig and t != name]
        for t in orphans:
            used.add(t)
        if orphans:
            plan.append({"bound": b, "phys": name, "cols": sorted(sig),
                         "orphans": orphans})

    if not plan:
        out["note"] = "no matching orphan tables — nothing to stitch"
        return out

    all_affected = []
    for p in plan:
        all_affected.append(p["phys"])
        all_affected.extend(p["orphans"])

    # 3) backup (pg_dump when available; always record pre-counts)
    with eng.connect() as conn:
        pre_counts = {t: _count(conn, schema, t) for t in all_affected}
    out["backup"] = {"pre_counts": pre_counts,
                     "dump_path": (None if dry_run else _pg_dump(schema, all_affected))}

    # 4) merge (single transaction). For dry_run we only COUNT would-add rows.
    for p in plan:
        bound_q = f"{_q(schema)}.{_q(p['phys'])}"
        cols = p["cols"]
        col_list = ", ".join(_q(c) for c in cols)
        dedupe = _dedupe_where(cols, bound_q)
        added_here = 0
        orphan_rows = []
        with eng.begin() as conn:
            for orphan in p["orphans"]:
                orphan_q = f"{_q(schema)}.{_q(orphan)}"
                if dry_run:
                    n = int(conn.execute(text(
                        f"SELECT count(*) FROM {orphan_q} o WHERE {dedupe}"
                    )).scalar() or 0)
                else:
                    res = conn.execute(text(
                        f"INSERT INTO {bound_q} ({col_list}) "
                        f"SELECT {col_list} FROM {orphan_q} o WHERE {dedupe}"
                    ))
                    n = int(res.rowcount or 0)
                added_here += n
                orphan_rows.append({"orphan": orphan, "rows_added": n})
            final_rows = _count(conn, schema, p["phys"])
        out["rows_added"] += added_here
        out["tables_stitched"] += len(p["orphans"])
        out["final_rows_by_dt"][p["bound"]["dt_id"]] = final_rows
        out["details"].append({
            "bound_table": p["phys"], "dt_id": p["bound"]["dt_id"],
            "dedupe_key": (_ROWKEY if _ROWKEY in cols
                           else _CONTENT_HASH if _CONTENT_HASH in cols
                           else "full-row"),
            "partition_cols": [c for c in _PARTITION_COLS if c in cols],
            "orphans": orphan_rows, "final_rows": final_rows,
        })

    # 5) drop merged orphans (only for real runs, after the merge committed)
    if drop_orphans and not dry_run:
        dropped = []
        with eng.begin() as conn:
            for p in plan:
                for orphan in p["orphans"]:
                    try:
                        conn.execute(text(
                            f"DROP TABLE IF EXISTS {_q(schema)}.{_q(orphan)}"))
                        dropped.append(orphan)
                    except Exception:  # noqa: BLE001
                        logger.warning("selfheal: drop failed for %s.%s",
                                       schema, orphan, exc_info=True)
        out["dropped"] = dropped

    return out


# --------------------------------------------------------------------------- #
# Async entry point                                                           #
# --------------------------------------------------------------------------- #
async def selfheal_data_source(db, *, organization, data_source,
                               dry_run: bool = False,
                               drop_orphans: bool = False) -> dict:
    """Stitch same-schema orphan staging tables back into a data source's bound
    table. Generic, multi-tenant, fail-soft. See module docstring."""
    result = {"ok": False, "tables_stitched": 0, "rows_added": 0,
              "final_rows": 0, "note": ""}
    try:
        from app.models.datasource_table import DataSourceTable
        from app.models.data_source import DataSource
        from app.services.ingest.tenant_schema import org_schema

        org_id = str(getattr(organization, "id", None)
                     or getattr(data_source, "organization_id", None) or "")
        if not org_id:
            result["note"] = "no organization id"
            return result
        schema = org_schema(org_id)

        # Bound/active physical tables for THIS data source.
        bound_rows = (await db.execute(
            select(DataSourceTable).where(
                DataSourceTable.datasource_id == str(data_source.id),
                DataSourceTable.is_active.is_(True),
                DataSourceTable.deleted_at.is_(None),
            )
        )).scalars().all()
        if not bound_rows:
            result["ok"] = True
            result["note"] = "no active bound tables for this data source"
            return result
        bound_list = [
            {"dt_id": str(r.id), "physical": _safe_name(r.name),
             "no_rows": int(r.no_rows or 0)}
            for r in bound_rows if r.name
        ]

        # Physical names CLAIMED by any live (non-deleted) datasource_table of any
        # non-deleted data source in THIS org — never steal these.
        claimed_rows = (await db.execute(
            select(DataSourceTable.name)
            .join(DataSource, DataSource.id == DataSourceTable.datasource_id)
            .where(
                DataSource.organization_id == org_id,
                DataSource.deleted_at.is_(None),
                DataSourceTable.deleted_at.is_(None),
            )
        )).all()
        claimed: set = set()
        for (nm,) in claimed_rows:
            if nm:
                claimed.add(nm)
                claimed.add(_safe_name(nm))

        # Physical work off the event loop (sync superuser engine).
        summary = await asyncio.to_thread(
            _heal_sync, schema, bound_list, claimed, dry_run, drop_orphans)

        result["tables_stitched"] = summary.get("tables_stitched", 0)
        result["rows_added"] = summary.get("rows_added", 0)
        final_by_dt = summary.get("final_rows_by_dt", {}) or {}
        result["final_rows"] = int(sum(v for v in final_by_dt.values() if v and v > 0))
        result["details"] = summary.get("details", [])
        if summary.get("backup"):
            result["backup"] = summary["backup"]
        if summary.get("dropped") is not None:
            result["dropped"] = summary["dropped"]

        # Persist the new physical counts onto datasource_tables.no_rows.
        if not dry_run and final_by_dt:
            try:
                for r in bound_rows:
                    fc = final_by_dt.get(str(r.id))
                    if fc is not None and fc >= 0:
                        r.no_rows = int(fc)
                await db.commit()
            except Exception:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass

        result["ok"] = True
        if summary.get("note"):
            result["note"] = summary["note"]
        else:
            result["note"] = (
                f"stitched {result['tables_stitched']} orphan table(s), "
                f"added {result['rows_added']} row(s)"
                + (" (dry-run)" if dry_run else "")
            )
        logger.info(
            "selfheal ds=%s org=%s: %s (rows_added=%s, final=%s%s)",
            getattr(data_source, "id", "?"), org_id, result["note"],
            result["rows_added"], result["final_rows"],
            ", dry-run" if dry_run else "",
        )
        return result
    except Exception as e:  # noqa: BLE001 — never raise into callers
        logger.warning("selfheal_data_source failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        result["ok"] = False
        result["note"] = f"selfheal error: {e}"
        return result
