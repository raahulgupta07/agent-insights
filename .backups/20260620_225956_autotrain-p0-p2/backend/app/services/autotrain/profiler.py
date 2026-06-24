"""Read-only table profiler producing a JSON-safe profile_v2 dict.

Never raises: on any error returns a safe empty/default profile.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
_NUMERIC_TYPES = ("int", "float", "numeric", "decimal", "double", "real", "serial", "money")


def _safe_ident(name: str) -> str:
    """Validate an identifier; raise ValueError if it contains anything unsafe."""
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return name


def _jsonable(v):
    try:
        if v is None:
            return None
        if isinstance(v, (int, str, bool)):
            return v
        if isinstance(v, float):
            return v
        if isinstance(v, datetime):
            return v.isoformat()
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
        return str(v)
    except Exception:
        return str(v)


def _is_numeric(dtype: str) -> bool:
    d = (dtype or "").lower()
    return any(t in d for t in _NUMERIC_TYPES) and "timestamp" not in d


def _empty_profile() -> dict:
    return {
        "row_count": 0,
        "columns": [],
        "profiled_at": datetime.now(timezone.utc).isoformat(),
    }


def profile_table(table: str, *, engine=None, schema: str = "staging", max_distinct: int = 500) -> dict:
    try:
        tbl = _safe_ident(table)
        sch = _safe_ident(schema)
    except Exception as e:
        logger.warning("profile_table: invalid identifiers: %s", e)
        return _empty_profile()

    try:
        if engine is None:
            from app.ai.code_execution.analytics_engine import get_analytics_readonly_engine
            engine = get_analytics_readonly_engine()
    except Exception as e:
        logger.warning("profile_table: cannot get engine: %s", e)
        return _empty_profile()

    qname = f'"{sch}"."{tbl}"'
    try:
        with engine.connect() as conn:
            row_count = conn.execute(text(f"SELECT COUNT(*) FROM {qname}")).scalar() or 0

            cols = conn.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"
                ),
                {"s": sch, "t": tbl},
            ).fetchall()

            columns = []
            for col_name, dtype in cols:
                columns.append(_profile_column(conn, qname, col_name, dtype, row_count, max_distinct))

            return {
                "row_count": int(row_count),
                "columns": columns,
                "profiled_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.warning("profile_table(%s): failed: %s", table, e)
        return _empty_profile()


def _profile_column(conn, qname: str, col_name: str, dtype: str, row_count: int, max_distinct: int) -> dict:
    out = {
        "name": col_name,
        "dtype": str(dtype),
        "role": "dimension",
        "distinct": 0,
        "null_pct": 0.0,
        "min": None,
        "max": None,
        "top_values": [],
    }
    try:
        c = f'"{_safe_ident(col_name)}"'
        numeric = _is_numeric(dtype)
        select = [
            f"COUNT(*) AS cnt",
            f"COUNT(DISTINCT {c}) AS distinct_count",
            f"COUNT(*) - COUNT({c}) AS null_count",
        ]
        if numeric:
            select += [f"MIN({c}) AS mn", f"MAX({c}) AS mx", f"AVG({c}) AS av"]
        row = conn.execute(text(f"SELECT {', '.join(select)} FROM {qname}")).mappings().first() or {}

        cnt = int(row.get("cnt") or 0)
        distinct = int(row.get("distinct_count") or 0)
        nulls = int(row.get("null_count") or 0)
        out["distinct"] = distinct
        out["null_pct"] = round((nulls / cnt) * 100, 2) if cnt else 0.0
        if numeric:
            out["min"] = _jsonable(row.get("mn"))
            out["max"] = _jsonable(row.get("mx"))

        name_l = (col_name or "").lower()
        is_id = name_l.endswith("_id") or (row_count and distinct >= row_count * 0.95)
        if is_id:
            out["role"] = "id"
        elif numeric:
            out["role"] = "measure"
        else:
            out["role"] = "dimension"

        if out["role"] == "dimension" and 0 < distinct <= max_distinct:
            tv = conn.execute(
                text(
                    f"SELECT {c} AS v, COUNT(*) AS n FROM {qname} "
                    f"WHERE {c} IS NOT NULL GROUP BY {c} ORDER BY n DESC LIMIT 10"
                )
            ).fetchall()
            out["top_values"] = [{"value": _jsonable(v), "count": int(n)} for v, n in tv]
    except Exception as e:
        logger.debug("_profile_column(%s): %s", col_name, e)
    return out
