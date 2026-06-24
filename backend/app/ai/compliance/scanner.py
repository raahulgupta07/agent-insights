"""Compliance & data-integrity scanner (Feature 4) — deterministic, code-only.

ON-DEMAND, advisory, READ-ONLY checks for a single data source. NOT wired into
the ingest pipeline (that is invasive + risky). Everything here runs plain
SELECT / COUNT / GROUP BY queries through the EXISTING data-source client layer
(`DataSource.get_client().aexecute_query(...)`) — the same path
`app/routes/knowledge.py::test_metric` (line ~470) uses to run ad-hoc SQL
against the live engine (DuckDB for the spreadsheet connector). No pandas-on-disk.

Two source-agnostic checks for any tabular data source:
  1. DEDUP        — rows sharing a contact phone are possible duplicates.
  2. DATA QUALITY — required identity/geo/contact fields missing.
Required fields are DERIVED from the live schema (see `_derive_required_fields`);
they are not hardcoded to any particular dataset. Plus a combined compliance
summary the UI can render.

Each check is fail-soft: a failing check returns its own ``{"error": ...}``
payload and never raises into the route, so one broken check cannot 500 the
whole scan.

The module is intentionally dependency-light (stdlib + the client layer) and
LLM-free: every number here is computed by SQL, not generated.
"""

from __future__ import annotations

import re
from typing import Any, Optional


# Read-only guard (self-contained copy of the proven knowledge-route guard so
# this module has no route-layer import dependency). Defence-in-depth: every
# query the scanner builds is also passed through this before execution.
_WRITE_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "merge", "replace", "call", "exec",
    "execute", "vacuum", "comment", "lock", "set", "begin", "commit",
    "rollback", "savepoint",
)


def _is_read_only_sql(sql: str) -> bool:
    """True only for a single read statement starting with SELECT or WITH."""
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
    # Strip quoted idents + string literals so a column like "Call Type" doesn't
    # trip the CALL keyword.
    scan = re.sub(r'"[^"]*"', " ", lowered)
    scan = re.sub(r"'[^']*'", " ", scan)
    for kw in _WRITE_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", scan):
            return False
    return True


# Generic fallback when schema introspection finds no importance columns
# (last resort only — required fields are normally DERIVED from the live schema
# via `_derive_required_fields`, and an explicit per-request list always wins).
DEFAULT_REQUIRED_FIELDS = ["City", "District"]

# Phone-like column auto-pick pattern. Source-agnostic: matches common contact
# column names; returns None (dedup skipped) when a source has no such column.
_PHONE_RE = re.compile(r"phone|contact|mobile|tel", re.IGNORECASE)

# Importance patterns used to DERIVE required fields from any schema (Task 1).
# Ordered by preference so the derived set is diverse: geo + name + id + contact.
_IMPORTANCE_PATTERNS = [
    ("geo", re.compile(
        r"city|state|province|district|region|township|country|zip|postal",
        re.IGNORECASE)),
    ("name", re.compile(r"\bname\b", re.IGNORECASE)),
    ("id", re.compile(r"\bid\b|code", re.IGNORECASE)),
    ("contact", re.compile(r"phone|email|mobile|contact", re.IGNORECASE)),
    ("date", re.compile(r"date", re.IGNORECASE)),
]

# Cap on duplicate-group sample rows returned to the UI.
_SAMPLE_LIMIT = 20

# Max raw scan rows we will materialize for the dedup GROUP BY safety cap.
_DEDUP_GROUP_LIMIT = 500


def _quote_ident(name: str) -> str:
    """Quote a SQL identifier (table or column) for DuckDB / generic SQL.

    Doubles any embedded double-quotes. Used so column/table names that contain
    spaces or mixed case (e.g. "City", "District/region") are safe and exact.
    """
    return '"' + str(name).replace('"', '""') + '"'


def _jsonable(v: Any) -> Any:
    """Coerce a cell value to something JSON-serializable."""
    if v is None:
        return None
    try:
        import math

        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
    except Exception:
        pass
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _pick_phone_column(columns: list[str], hint: Optional[str]) -> Optional[str]:
    """Return the phone column to dedup on.

    If `hint` is given and matches a real column (case-insensitive), use it.
    Otherwise auto-pick the first column whose name matches /phone|contact|mobile/i.
    Returns None when nothing matches (the Abbott dataset has no phone column).
    """
    if hint:
        for c in columns:
            if str(c).lower() == hint.lower():
                return c
        # An explicit hint that doesn't exist -> treat as not found.
        return None
    for c in columns:
        if _PHONE_RE.search(str(c)):
            return c
    return None


def _resolve_columns(client, table_name: str) -> list[str]:
    """Get the real column names for `table_name` from the client schema.

    Uses the client's `get_schema`/`get_schemas` (the live engine introspection,
    same objects the agent sees) so we match the physical DuckDB column casing.
    """
    try:
        tbl = client.get_schema(table_name)
        cols = [c.name for c in getattr(tbl, "columns", []) or []]
        if cols:
            return cols
    except Exception:
        pass
    # Fall back to scanning all schemas for the matching table.
    try:
        for t in client.get_schemas() or []:
            if str(t.name) == str(table_name):
                return [c.name for c in getattr(t, "columns", []) or []]
    except Exception:
        pass
    return []


def _resolve_table_name(client, preferred: Optional[str]) -> Optional[str]:
    """Resolve the physical table to scan.

    If `preferred` is given and exists, use it. Otherwise pick the first base
    table the client exposes (spreadsheet sources are single-table in practice).
    """
    try:
        schemas = client.get_schemas() or []
    except Exception:
        return preferred
    names = [str(t.name) for t in schemas]
    if preferred and preferred in names:
        return preferred
    if preferred:
        # Case-insensitive match.
        for n in names:
            if n.lower() == preferred.lower():
                return n
    return names[0] if names else preferred


async def _scalar(client, sql: str) -> Optional[Any]:
    """Run a single-cell read-only query and return cell[0][0] (or None)."""
    if not _is_read_only_sql(sql):
        raise ValueError("internal: non read-only SQL blocked")
    df = await client.aexecute_query(sql)
    if df is None or len(df) == 0 or len(df.columns) == 0:
        return None
    return df.iloc[0, 0]


async def run_dedup_check(
    client,
    table_name: str,
    columns: list[str],
    phone_column: Optional[str],
) -> dict:
    """DEDUP: group rows by the phone column, find groups with COUNT(*) > 1.

    Returns one of:
      - {"status": "skipped", "reason": "no phone-like column found", ...}
      - {"status": "ok", "phone_column", "duplicate_groups", "duplicate_rows",
         "sample": [{"value", "count"}, ...]}
      - {"status": "error", "error": "..."}
    """
    try:
        col = _pick_phone_column(columns, phone_column)
        if not col:
            return {
                "status": "skipped",
                "reason": "no phone-like column found",
                "hint": "pass phone_column in the request body to force a column",
                "duplicate_groups": 0,
                "duplicate_rows": 0,
                "sample": [],
            }

        qt = _quote_ident(table_name)
        qc = _quote_ident(col)

        # Duplicate groups + total rows in those groups, plus a sample.
        # We compute a grouped subquery once and aggregate over it.
        sample_sql = (
            f"SELECT {qc} AS value, COUNT(*) AS cnt "
            f"FROM {qt} "
            f"WHERE {qc} IS NOT NULL AND CAST({qc} AS VARCHAR) <> '' "
            f"GROUP BY {qc} HAVING COUNT(*) > 1 "
            f"ORDER BY cnt DESC LIMIT {_DEDUP_GROUP_LIMIT}"
        )
        if not _is_read_only_sql(sample_sql):
            return {"status": "error", "error": "internal: dedup SQL blocked"}
        df = await client.aexecute_query(sample_sql)

        duplicate_groups = int(len(df)) if df is not None else 0
        sample: list[dict] = []
        duplicate_rows = 0
        if df is not None and len(df) > 0:
            for _i, row in df.iterrows():
                cnt = int(row["cnt"])
                duplicate_rows += cnt
                if len(sample) < _SAMPLE_LIMIT:
                    sample.append({"value": _jsonable(row["value"]), "count": cnt})

        return {
            "status": "ok",
            "phone_column": col,
            "duplicate_groups": duplicate_groups,
            "duplicate_rows": duplicate_rows,
            "sample": sample,
        }
    except Exception as e:  # noqa: BLE001 — fail-soft per-check
        return {"status": "error", "error": str(e)}


async def run_quality_check(
    client,
    table_name: str,
    columns: list[str],
    required_fields: list[str],
) -> dict:
    """DATA QUALITY: per required field, count rows where it is NULL or ''.

    quality_score = 1 - avg(missing_pct over fields that actually exist).
    A required field not present in the schema is reported as missing=True but
    excluded from the score average (we can't measure what isn't there).
    """
    try:
        qt = _quote_ident(table_name)
        # Total row count once.
        total = await _scalar(client, f"SELECT COUNT(*) FROM {qt}")
        total = int(total) if total is not None else 0

        lower_cols = {str(c).lower(): str(c) for c in columns}
        fields_report: list[dict] = []
        measured_pcts: list[float] = []

        for field in required_fields:
            real = lower_cols.get(str(field).lower())
            if real is None:
                fields_report.append(
                    {
                        "field": field,
                        "present": False,
                        "missing_count": None,
                        "missing_pct": None,
                        "note": "column not found in schema",
                    }
                )
                continue

            qc = _quote_ident(real)
            if total == 0:
                missing = 0
                pct = 0.0
            else:
                m = await _scalar(
                    client,
                    f"SELECT COUNT(*) FROM {qt} "
                    f"WHERE {qc} IS NULL OR CAST({qc} AS VARCHAR) = ''",
                )
                missing = int(m) if m is not None else 0
                pct = round(missing / total, 4) if total else 0.0
            measured_pcts.append(pct)
            fields_report.append(
                {
                    "field": real,
                    "present": True,
                    "missing_count": missing,
                    "missing_pct": pct,
                }
            )

        if measured_pcts:
            avg_missing = sum(measured_pcts) / len(measured_pcts)
            quality_score = round(1.0 - avg_missing, 4)
        else:
            quality_score = None  # no measurable required field

        return {
            "status": "ok",
            "total_rows": total,
            "required_fields": [str(f) for f in required_fields],
            "fields": fields_report,
            "quality_score": quality_score,
        }
    except Exception as e:  # noqa: BLE001 — fail-soft per-check
        return {"status": "error", "error": str(e)}


def _build_summary(table_name: str, dedup: dict, quality: dict) -> dict:
    """Build a compact compliance summary the UI can show at a glance."""
    issues: list[str] = []

    if dedup.get("status") == "ok" and dedup.get("duplicate_groups", 0) > 0:
        issues.append(
            f"{dedup['duplicate_groups']} possible duplicate contact group(s) "
            f"({dedup['duplicate_rows']} rows) on '{dedup.get('phone_column')}'"
        )

    if quality.get("status") == "ok":
        for f in quality.get("fields", []):
            if f.get("present") and (f.get("missing_count") or 0) > 0:
                issues.append(
                    f"{f['missing_count']} rows missing '{f['field']}' "
                    f"({round((f.get('missing_pct') or 0) * 100, 1)}%)"
                )
            elif not f.get("present"):
                issues.append(f"required field '{f['field']}' not present")

    quality_score = quality.get("quality_score") if quality.get("status") == "ok" else None

    # A coarse traffic-light status for the UI.
    if quality_score is None:
        overall = "unknown"
    elif quality_score >= 0.95 and not issues:
        overall = "pass"
    elif quality_score >= 0.8:
        overall = "warn"
    else:
        overall = "fail"

    return {
        "table": table_name,
        "overall": overall,
        "quality_score": quality_score,
        "issue_count": len(issues),
        "issues": issues,
    }


async def _derive_required_fields(data_source, *, cap: int = 6) -> list[str]:
    """Derive "important" required fields from the live schema (source-agnostic).

    Introspects every table's columns via the data source's client and picks a
    diverse, deduped, capped set of identity/geo/contact-style columns whose NAME
    matches the importance patterns in `_IMPORTANCE_PATTERNS` (geo + name + id +
    contact + date), preferring geo/name/id/contact for breadth.

    Returns [] when introspection fails or no importance column is found (NOT a
    hardcoded list — the caller decides whether to fall back). Never raises.
    """
    try:
        client = data_source.get_client()
    except Exception:
        return []

    # Collect candidate column names across all tables.
    columns: list[str] = []
    try:
        for t in client.get_schemas() or []:
            for c in getattr(t, "columns", []) or []:
                nm = getattr(c, "name", None)
                if nm:
                    columns.append(str(nm))
    except Exception:
        return []

    if not columns:
        return []

    # Group matches by importance category, preserving first-seen order and
    # de-duping case-insensitively across the whole pick.
    by_category: dict[str, list[str]] = {cat: [] for cat, _ in _IMPORTANCE_PATTERNS}
    seen_lower: set[str] = set()
    for col in columns:
        low = col.lower()
        if low in seen_lower:
            continue
        for category, pattern in _IMPORTANCE_PATTERNS:
            if pattern.search(col):
                by_category[category].append(col)
                seen_lower.add(low)
                break  # one category per column (first match wins)

    # Round-robin across categories so the picked set is DIVERSE, not all geo.
    picked: list[str] = []
    indices = {cat: 0 for cat, _ in _IMPORTANCE_PATTERNS}
    order = [cat for cat, _ in _IMPORTANCE_PATTERNS]
    progressed = True
    while len(picked) < cap and progressed:
        progressed = False
        for category in order:
            i = indices[category]
            bucket = by_category.get(category, [])
            if i < len(bucket):
                picked.append(bucket[i])
                indices[category] = i + 1
                progressed = True
                if len(picked) >= cap:
                    break

    return picked[:cap]


async def scan_data_source(
    data_source,
    *,
    phone_column: Optional[str] = None,
    required_fields: Optional[list[str]] = None,
    table_name: Optional[str] = None,
) -> dict:
    """Run the full compliance scan for a DataSource (advisory, read-only).

    `data_source` is a loaded `DataSource` ORM row whose `connections` are
    available (lazy="selectin" -> already eager-loaded after an async query).

    Returns a combined report dict. Never raises: client acquisition / schema
    introspection failures are reported as a top-level error; per-check failures
    are isolated inside each check's payload.
    """
    # Resolve required fields (Task 2): an explicit per-request list always wins;
    # otherwise DERIVE them from the live schema; only if that yields nothing do
    # we fall back to the generic DEFAULT_REQUIRED_FIELDS constant.
    if required_fields:
        req_fields = list(required_fields)
    else:
        derived = await _derive_required_fields(data_source)
        req_fields = derived if derived else list(DEFAULT_REQUIRED_FIELDS)

    # 1. Acquire a query client via the SAME path the agent/knowledge route uses.
    try:
        client = data_source.get_client()
    except Exception as e:  # noqa: BLE001
        return {
            "data_source_id": str(getattr(data_source, "id", "")),
            "ok": False,
            "error": f"could not obtain data-source client: {e}",
        }

    # 2. Resolve the physical table + columns from the live engine schema.
    try:
        resolved_table = _resolve_table_name(client, table_name)
        if not resolved_table:
            return {
                "data_source_id": str(data_source.id),
                "ok": False,
                "error": "no table found in data source schema",
            }
        columns = _resolve_columns(client, resolved_table)
    except Exception as e:  # noqa: BLE001
        return {
            "data_source_id": str(data_source.id),
            "ok": False,
            "error": f"schema introspection failed: {e}",
        }

    # 3. Run the deterministic checks (each fail-soft).
    dedup = await run_dedup_check(client, resolved_table, columns, phone_column)
    quality = await run_quality_check(client, resolved_table, columns, req_fields)

    summary = _build_summary(resolved_table, dedup, quality)

    return {
        "data_source_id": str(data_source.id),
        "data_source_name": getattr(data_source, "name", None),
        "table": resolved_table,
        "columns": columns,
        "ok": True,
        "summary": summary,
        "dedup": dedup,
        "quality": quality,
    }
