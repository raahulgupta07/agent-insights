"""Column Intelligence profiler (Batch B / Phase 2) — deterministic, code-only.

PRE-TRAIN per-column profiling so the agent KNOWS each column up front: its
type, its semantic ROLE (dimension / measure / id / date), how many distinct
values, how many nulls, numeric min/max, and — for low-cardinality dimensions —
the actual list of VALUES (e.g. Brand -> [Ensure, Glucerna, ...]).

Runs through the SAME data-source client path the compliance scanner and the
knowledge route use (`DataSource.get_client().aexecute_query(...)`), so every
number is computed by SQL against the LIVE engine (DuckDB for the spreadsheet
connector), never pandas-on-disk and never an LLM guess.

The result is merged into ``DataSourceTable.columns[].metadata`` (keys: role,
values, distinct, null_pct, min, max) by the route layer, where the existing
schema renderer already surfaces ``metadata.role`` and (after Batch B) the
``metadata.values`` list into the agent's <column .../> schema XML.

Fail-soft: any per-column error is swallowed and that column keeps default
inferred values; client/schema failures return a top-level {ok: False, error}.

NOTE: deliberately NO `from __future__ import annotations` to stay consistent
with the body+permission route landmine elsewhere in this codebase.
"""

import math
import re
from typing import Any, List, Optional


# ── read-only guard (self-contained copy, defence-in-depth) ─────────────────
_WRITE_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "merge", "replace", "call", "exec",
    "execute", "vacuum", "comment", "lock", "set", "begin", "commit",
    "rollback", "savepoint",
)

# numeric dtype fragments (covers PG + DuckDB spelling)
_NUMERIC_TYPES = ("int", "float", "numeric", "decimal", "double", "real",
                  "serial", "money", "bigint", "smallint", "hugeint", "tinyint")
# temporal dtype fragments
_DATE_TYPES = ("date", "timestamp", "time", "datetime", "interval")
# name patterns hinting a date even when stored as text
_DATE_NAME_RE = re.compile(r"\b(date|month|year|day|quarter|week|period|_at)\b|month$|year$", re.IGNORECASE)
# name patterns hinting an identifier
_ID_NAME_RE = re.compile(r"(^id$|_id$|^.*id$|code$|uuid|guid)", re.IGNORECASE)

# cap: only dimensions with <= this many distinct values get a VALUES list
# (raised 50 -> 200 so low/medium-cardinality dims like Call Type / Outcome /
# Category always get a sample VALUES list; the stored list is still capped to
# the top _TOP_VALUES_LIMIT entries).
_VALUES_CARDINALITY_CAP = 200
# how many top values to store
_TOP_VALUES_LIMIT = 20


def _is_read_only_sql(sql: str) -> bool:
    if not sql or not sql.strip():
        return False
    cleaned = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    cleaned = re.sub(r"--[^\n]*", " ", cleaned).strip()
    if not cleaned:
        return False
    body = cleaned.rstrip().rstrip(";")
    if ";" in body:
        return False
    lowered = body.lower()
    parts = lowered.split(None, 1)
    first = parts[0] if parts else ""
    if first not in ("select", "with"):
        return False
    # Strip "quoted identifiers" + 'string literals' before the write-keyword
    # scan so a column named e.g. "Call Type"/"Call Outcome" doesn't trip the
    # CALL keyword (real DML still leads with its keyword, caught above/here).
    scan = re.sub(r'"[^"]*"', " ", lowered)
    scan = re.sub(r"'[^']*'", " ", scan)
    for kw in _WRITE_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", scan):
            return False
    return True


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
    except Exception:
        pass
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _is_numeric(dtype: str) -> bool:
    d = (dtype or "").lower()
    return any(t in d for t in _NUMERIC_TYPES) and "timestamp" not in d and "date" not in d


def _is_date(dtype: str, name: str) -> bool:
    d = (dtype or "").lower()
    if any(t in d for t in _DATE_TYPES):
        return True
    return bool(_DATE_NAME_RE.search(name or ""))


def _classify_role(name: str, dtype: str, distinct: int, row_count: int) -> str:
    """dimension | measure | id | date — rule-based, no LLM."""
    name_l = (name or "")
    near_unique = bool(row_count) and distinct is not None and distinct > 1 and distinct >= row_count * 0.95
    # id ONLY when the name says id/code/key — a near-unique TEXT column is a
    # high-cardinality dimension (names, titles, store names), NOT an id.
    if _ID_NAME_RE.search(name_l):
        return "id"
    # date wins over the surrogate-key rule (a near-unique date is still a date).
    if _is_date(dtype, name_l):
        return "date"
    if _is_numeric(dtype):
        # near-unique numeric with no id-name = surrogate key; else a measure.
        if near_unique:
            return "id"
        # numeric but very low distinct + name not measure-y -> still a measure,
        # the agent can GROUP BY it if needed; measure is the safe default.
        return "measure"
    return "dimension"


def _resolve_table_columns(client, preferred_table: Optional[str]):
    """Return (table_name, [(col_name, dtype), ...]) from the live engine schema."""
    try:
        schemas = client.get_schemas() or []
    except Exception:
        schemas = []
    names = [str(t.name) for t in schemas]

    target = None
    if preferred_table and preferred_table in names:
        target = preferred_table
    elif preferred_table:
        for n in names:
            if n.lower() == preferred_table.lower():
                target = n
                break
    if target is None and names:
        target = names[0]

    cols: List[tuple] = []
    if target is not None:
        for t in schemas:
            if str(t.name) == str(target):
                for c in getattr(t, "columns", []) or []:
                    cols.append((c.name, getattr(c, "dtype", None) or "unknown"))
                break
    return target, cols


async def _profile_column(client, qt: str, name: str, dtype: str, row_count: int) -> dict:
    # NOTE: ``distinct`` starts as None (= "not computed / count failed"), NOT 0.
    # 0 would falsely render an empty cell for a column we simply couldn't count;
    # a real all-NULL column legitimately returns distinct == 0 from the query.
    out = {
        "name": name,
        "dtype": str(dtype or "unknown"),
        "role": "dimension",
        "distinct": None,
        "null_pct": 0.0,
        "min": None,
        "max": None,
        "values": [],
    }

    qc = _quote_ident(name)
    numeric = _is_numeric(dtype)
    distinct = None  # local mirror used for role + values gating

    # ── (a) ALWAYS compute distinct/null_pct/min-max for EVERY column ─────────
    try:
        select = [
            "COUNT(*) AS cnt",
            f"COUNT(DISTINCT {qc}) AS distinct_count",
            f"COUNT(*) - COUNT({qc}) AS null_count",
        ]
        if numeric:
            select += [f"MIN({qc}) AS mn", f"MAX({qc}) AS mx"]
        sql = f"SELECT {', '.join(select)} FROM {qt}"
        if _is_read_only_sql(sql):
            df = await client.aexecute_query(sql)
            if df is not None and len(df) > 0:
                row = df.iloc[0]
                cnt = int(row.get("cnt") or 0)
                dc = row.get("distinct_count")
                distinct = int(dc) if dc is not None else None
                nulls = int(row.get("null_count") or 0)
                out["distinct"] = distinct
                out["null_pct"] = round((nulls / cnt) * 100, 2) if cnt else 0.0
                if numeric:
                    out["min"] = _jsonable(row.get("mn"))
                    out["max"] = _jsonable(row.get("mx"))
    except Exception:
        # leave distinct = None (count failed) — NOT 0.
        distinct = None
        out["distinct"] = None

    # ── (b) ALWAYS assign a role, even for high-distinct / un-counted columns ─
    # _classify_role tolerates distinct == None (id/date/measure rules don't
    # need it; the near-unique-id check only triggers on a real number).
    try:
        out["role"] = _classify_role(name, dtype, distinct if distinct is not None else 0, row_count)
    except Exception:
        out["role"] = "dimension"

    # ── (c) VALUES list for ANY dimension with 1 <= distinct <= CAP (200) ─────
    # High-distinct dims (> cap) and un-counted dims (distinct None) get role +
    # distinct but no values list — that's fine.
    try:
        if (
            out["role"] == "dimension"
            and distinct is not None
            and 0 < distinct <= _VALUES_CARDINALITY_CAP
        ):
            tv_sql = (
                f"SELECT {qc} AS v, COUNT(*) AS n FROM {qt} "
                f"WHERE {qc} IS NOT NULL AND CAST({qc} AS VARCHAR) <> '' "
                f"GROUP BY {qc} ORDER BY n DESC LIMIT {_TOP_VALUES_LIMIT}"
            )
            if _is_read_only_sql(tv_sql):
                tdf = await client.aexecute_query(tv_sql)
                if tdf is not None and len(tdf) > 0:
                    out["values"] = [_jsonable(v) for v in tdf["v"].tolist()]
    except Exception:
        pass

    return out


async def profile_data_source(data_source, *, table_name: Optional[str] = None) -> dict:
    """Profile every column of a data source's (single) table, read-only.

    Returns:
      {ok, data_source_id, table, row_count, columns: [ {name, dtype, role,
       distinct, null_pct, min, max, values}, ... ]}
    or {ok: False, error} on client/schema failure. Never raises.
    """
    try:
        client = data_source.get_client()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "data_source_id": str(getattr(data_source, "id", "")),
                "error": f"could not obtain data-source client: {e}"}

    try:
        target, cols = _resolve_table_columns(client, table_name)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "data_source_id": str(getattr(data_source, "id", "")),
                "error": f"schema introspection failed: {e}"}

    if not target or not cols:
        return {"ok": False, "data_source_id": str(getattr(data_source, "id", "")),
                "error": "no table/columns found in data source schema"}

    qt = _quote_ident(target)
    try:
        row_count = 0
        rc_sql = f"SELECT COUNT(*) AS n FROM {qt}"
        if _is_read_only_sql(rc_sql):
            rdf = await client.aexecute_query(rc_sql)
            if rdf is not None and len(rdf) > 0:
                row_count = int(rdf.iloc[0, 0] or 0)
    except Exception:
        row_count = 0

    columns = []
    for name, dtype in cols:
        columns.append(await _profile_column(client, qt, name, dtype, row_count))

    return {
        "ok": True,
        "data_source_id": str(getattr(data_source, "id", "")),
        "data_source_name": getattr(data_source, "name", None),
        "table": target,
        "row_count": row_count,
        "columns": columns,
    }
