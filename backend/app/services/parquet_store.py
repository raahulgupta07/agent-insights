"""Parquet result storage for step results.

Large step result sets (the ``{"rows": [...], "columns": [...], "info": {...}}``
dict produced by ``format_df_for_widget``) are written to a compressed Parquet
file on disk instead of stored inline as JSON in Postgres. This shrinks the DB
(and ``pg_dump``), speeds dashboard loads, and lets future interactive queries run
DuckDB pushdown over the file.

Design:
  * Gated by ``flags.PARQUET_RESULTS`` (default OFF) + a row-count threshold
    (``flags.PARQUET_MIN_ROWS``). Below threshold, results stay inline (today's path).
  * When offloaded, ``step.data`` keeps the cheap metadata inline
    (``columns`` + ``info``) plus a marker; ``rows`` is emptied inline and
    hydrated transparently on read from the Parquet file.
  * Crash-safe ordering: the file is written BEFORE the marker row is committed,
    so a marker always points at an existing file (a missing file on read is
    treated as an empty/stale result, never a hard error).
  * GC: ``sweep_orphans`` deletes Parquet files no longer referenced by any step.

Marker shape stored in ``step.data`` when offloaded:
    {
      "__parquet__": 1,            # marker version
      "path": "uploads/parquet/<uuid>.parquet",
      "columns": [...],            # kept inline (table headers, cheap)
      "info": {...},               # kept inline (row/col counts, cheap)
      "rows": []                   # emptied inline; hydrated on read
    }
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_MARKER = "__parquet__"


def _base_dir() -> str:
    """Directory for result Parquet files (sibling of uploads/files)."""
    d = os.path.join(os.getcwd(), "uploads", "parquet")
    os.makedirs(d, exist_ok=True)
    return d


def _abs(rel_or_abs: str) -> str:
    if os.path.isabs(rel_or_abs):
        return rel_or_abs
    return os.path.join(os.getcwd(), rel_or_abs)


def is_offloaded(data: Any) -> bool:
    return isinstance(data, dict) and bool(data.get(_MARKER))


def _row_count(data: dict) -> int:
    info = data.get("info") if isinstance(data, dict) else None
    if isinstance(info, dict) and isinstance(info.get("total_rows"), int):
        return info["total_rows"]
    rows = data.get("rows") if isinstance(data, dict) else None
    return len(rows) if isinstance(rows, list) else 0


def should_offload(data: Any) -> bool:
    """True when this result is a row-bearing widget dict large enough to offload
    AND the feature flag is on."""
    from app.settings.hybrid_flags import flags
    if not flags.PARQUET_RESULTS:
        return False
    if not isinstance(data, dict) or is_offloaded(data):
        return False
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    return _row_count(data) >= flags.PARQUET_MIN_ROWS


def write_result(data: dict) -> dict:
    """Write ``data['rows']`` to a fresh Parquet file and return the inline marker
    dict to store in ``step.data``. Falls back to returning ``data`` unchanged on
    any failure (so a write error never loses the result — it just stays inline)."""
    rows = data.get("rows") or []
    base = _base_dir()  # ensures uploads/parquet exists
    fname = f"{uuid.uuid4().hex}.parquet"
    abs_path = os.path.join(base, fname)
    rel_path = os.path.join("uploads", "parquet", fname)
    try:
        import duckdb
        import pandas as pd
        df = pd.DataFrame(rows)
        con = duckdb.connect(database=":memory:")
        try:
            con.register("t", df)
            safe = abs_path.replace("'", "''")
            con.execute(f"COPY t TO '{safe}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        finally:
            con.close()
    except Exception:
        logger.exception("parquet write failed; keeping result inline")
        return data
    return {
        _MARKER: 1,
        "path": rel_path,
        "columns": data.get("columns", []),
        "info": data.get("info", {}),
        "rows": [],
    }


def maybe_offload(data: Any) -> Any:
    """Single entry point for write sites: returns a Parquet marker dict when the
    result is large enough and the flag is on, else the original ``data``."""
    if should_offload(data):
        return write_result(data)
    return data


def hydrate(data: Any) -> Any:
    """If ``data`` is a Parquet marker, return a full widget dict with ``rows``
    loaded from the file. Otherwise return ``data`` unchanged. Never raises — a
    missing/corrupt file yields an empty ``rows`` list (treated as stale)."""
    if not is_offloaded(data):
        return data
    out = {k: v for k, v in data.items() if k != _MARKER}
    # Tag the source so clients (dashboard) can opt into the interactive
    # /steps/{id}/query endpoint for filter/sort/page pushdown. Rows are still
    # hydrated here for full compatibility (CSV/PDF/agent paths).
    out["source"] = "parquet"
    abs_path = _abs(str(data.get("path", "")))
    if not abs_path or not os.path.exists(abs_path):
        logger.warning("parquet result file missing: %s", data.get("path"))
        out["rows"] = []
        return out
    try:
        import duckdb
        con = duckdb.connect(database=":memory:")
        try:
            safe = abs_path.replace("'", "''")
            df = con.execute(f"SELECT * FROM read_parquet('{safe}')").fetch_df()
        finally:
            con.close()
        import json as _json
        out["rows"] = _json.loads(df.to_json(orient="records", date_format="iso", default_handler=str))
    except Exception:
        logger.exception("parquet read failed for %s; returning empty rows", data.get("path"))
        out["rows"] = []
    return out


_ALLOWED_OPS = {"=", "!=", ">", ">=", "<", "<=", "in", "contains"}
_ALLOWED_AGG_FNS = {"sum", "avg", "min", "max", "count"}


def _quote_ident(name: str) -> str:
    """Quote a column identifier for DuckDB. ``name`` is ALWAYS validated against
    the known-fields allow-list before reaching here, but we still double any
    embedded double-quote defensively."""
    return '"' + str(name).replace('"', '""') + '"'


def query(step_data: dict, spec: dict) -> dict:
    """Run a declarative, ALLOW-LISTED query over a step's result set (Parquet or
    inline) and return ``{"rows", "columns", "total_rows", "source", "ms"}``.

    No raw SQL is accepted from the caller: the SQL is built here from the
    allow-lists below, and every value is bound as a DuckDB parameter. Any
    validation failure raises ``ValueError`` (so the route returns 400).
    """
    import time

    t0 = time.perf_counter()

    spec = spec or {}
    step_data = step_data or {}

    # --- known fields (allow-list of column names) -------------------------
    cols_meta = step_data.get("columns") or []
    known_fields = {
        c.get("field")
        for c in cols_meta
        if isinstance(c, dict) and c.get("field")
    }

    def _check_col(col: str, *, allow_aliases: set | None = None) -> str:
        if not isinstance(col, str):
            raise ValueError(f"Invalid column: {col!r}")
        if col in known_fields:
            return col
        if allow_aliases and col in allow_aliases:
            return col
        raise ValueError(f"Unknown column: {col!r}")

    # --- spec parsing ------------------------------------------------------
    select = spec.get("select") or []
    filters = spec.get("filters") or []
    group_by = spec.get("group_by") or []
    aggs = spec.get("aggs") or []
    order_by = spec.get("order_by") or []

    limit = spec.get("limit")
    limit = 100 if limit is None else int(limit)
    if limit < 0:
        limit = 0
    limit = min(limit, 5000)  # hard cap

    offset = spec.get("offset")
    offset = 0 if offset is None else int(offset)
    if offset < 0:
        offset = 0

    params: list[Any] = []

    # --- SELECT / aggs -----------------------------------------------------
    alias_names: set = set()
    select_parts: list[str] = []

    for col in group_by:
        _check_col(col)
    for col in group_by:
        select_parts.append(_quote_ident(col))

    for agg in aggs:
        if not isinstance(agg, dict):
            raise ValueError(f"Invalid agg: {agg!r}")
        fn = agg.get("fn")
        if fn not in _ALLOWED_AGG_FNS:
            raise ValueError(f"Disallowed agg fn: {fn!r}")
        alias = agg.get("as")
        if not isinstance(alias, str) or not alias:
            raise ValueError(f"Agg requires an 'as' alias: {agg!r}")
        agg_col = agg.get("col")
        if fn == "count" and (agg_col is None or agg_col == "*"):
            expr = "count(*)"
        else:
            _check_col(agg_col)
            expr = f"{fn}({_quote_ident(agg_col)})"
        alias_names.add(alias)
        select_parts.append(f"{expr} AS {_quote_ident(alias)}")

    # plain select columns (only when not aggregating)
    if not aggs:
        for col in select:
            _check_col(col)
        for col in select:
            select_parts.append(_quote_ident(col))

    select_clause = ", ".join(select_parts) if select_parts else "*"

    # --- FROM --------------------------------------------------------------
    con = None
    source: str
    try:
        import duckdb

        con = duckdb.connect(database=":memory:")

        if is_offloaded(step_data):
            abs_path = _abs(str(step_data.get("path", "")))
            safe = abs_path.replace("'", "''")  # path is not user input
            from_clause = f"read_parquet('{safe}')"
            source = "parquet"
        else:
            import pandas as pd

            rows = step_data.get("rows") or []
            con.register("t", pd.DataFrame(rows))
            from_clause = "t"
            source = "inline"

        # --- WHERE ---------------------------------------------------------
        where_parts: list[str] = []
        for f in filters:
            if not isinstance(f, dict):
                raise ValueError(f"Invalid filter: {f!r}")
            col = f.get("col")
            op = f.get("op")
            val = f.get("val")
            _check_col(col)
            if op not in _ALLOWED_OPS:
                raise ValueError(f"Disallowed op: {op!r}")
            qcol = _quote_ident(col)
            if op == "in":
                if not isinstance(val, (list, tuple)):
                    raise ValueError("'in' op requires a list value")
                if not val:
                    # empty IN -> matches nothing
                    where_parts.append("1=0")
                    continue
                placeholders = []
                for v in val:
                    params.append(v)
                    placeholders.append(f"${len(params)}")
                where_parts.append(f"{qcol} IN ({', '.join(placeholders)})")
            elif op == "contains":
                params.append(val)
                where_parts.append(f"{qcol} ILIKE '%'||${len(params)}||'%'")
            else:
                params.append(val)
                where_parts.append(f"{qcol} {op} ${len(params)}")

        where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # --- GROUP BY ------------------------------------------------------
        group_clause = ""
        if group_by:
            group_clause = " GROUP BY " + ", ".join(_quote_ident(c) for c in group_by)

        # inner query (no order/limit/offset) for the count
        inner = f"SELECT {select_clause} FROM {from_clause}{where_clause}{group_clause}"

        # --- total_rows ----------------------------------------------------
        count_sql = f"SELECT count(*) FROM ({inner}) AS _sub"
        total_rows = int(con.execute(count_sql, params).fetchone()[0])

        # --- ORDER BY ------------------------------------------------------
        order_clause = ""
        if order_by:
            order_parts: list[str] = []
            for o in order_by:
                if not isinstance(o, dict):
                    raise ValueError(f"Invalid order_by: {o!r}")
                ocol = o.get("col")
                _check_col(ocol, allow_aliases=alias_names)
                direction = (o.get("dir") or "asc").lower()
                if direction not in ("asc", "desc"):
                    raise ValueError(f"Invalid order dir: {direction!r}")
                order_parts.append(f"{_quote_ident(ocol)} {direction.upper()}")
            order_clause = " ORDER BY " + ", ".join(order_parts)

        # --- full query with order/limit/offset ----------------------------
        full_sql = f"{inner}{order_clause} LIMIT {limit} OFFSET {offset}"
        df = con.execute(full_sql, params).fetch_df()

    except ValueError:
        raise
    except Exception as e:  # any DuckDB / pandas error -> 400
        raise ValueError(str(e))
    finally:
        if con is not None:
            con.close()

    import json as _json

    out_rows = _json.loads(
        df.to_json(orient="records", date_format="iso", default_handler=str)
    )
    out_cols = [{"headerName": c, "field": c} for c in df.columns]

    return {
        "rows": out_rows,
        "columns": out_cols,
        "total_rows": total_rows,
        "source": source,
        "ms": int((time.perf_counter() - t0) * 1000),
    }


def delete_file(data: Any) -> None:
    """Delete the Parquet file backing a marker (best-effort)."""
    if not is_offloaded(data):
        return
    abs_path = _abs(str(data.get("path", "")))
    try:
        if abs_path and os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        logger.exception("parquet delete failed for %s", data.get("path"))


async def sweep_orphans(db) -> dict:
    """Delete Parquet files not referenced by any step's marker. Returns a summary.

    A file is 'referenced' if some ``steps.data->>'path'`` equals its relative path
    (with ``data->>'__parquet__'`` set). Anything else on disk is an orphan
    (archived/deleted reports, crashed writes) and is removed."""
    from sqlalchemy import text
    base = _base_dir()
    try:
        on_disk = {f for f in os.listdir(base) if f.endswith(".parquet")}
    except FileNotFoundError:
        return {"deleted": 0, "kept": 0}
    rows = await db.execute(
        text("SELECT data->>'path' AS p FROM steps WHERE data->>'__parquet__' IS NOT NULL")
    )
    referenced = {os.path.basename(r[0]) for r in rows.fetchall() if r[0]}
    deleted = 0
    for fname in on_disk - referenced:
        try:
            os.remove(os.path.join(base, fname))
            deleted += 1
        except Exception:
            logger.exception("orphan parquet delete failed: %s", fname)
    return {"deleted": deleted, "kept": len(on_disk & referenced)}
