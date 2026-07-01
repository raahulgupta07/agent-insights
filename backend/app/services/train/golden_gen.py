"""Pipeline v1 (P4): logic-aware golden generator.

For each Definition (P3) it builds a verifiable SQL query — `SELECT COUNT(*)
... WHERE <predicate>` — over the data source's table, using the documented
predicate instead of guessing. The eval gate (P5) then runs each and keeps only
the ones whose count matches the definition's expected number.

When the source is ONE table (P1 one-table-merge) the FROM is clean
`FROM "crm"`. When it's still N same-schema monthly tables, the FROM falls back
to a `UNION ALL` subquery so generation still works (but P1 is the better path).

Pure SQL builders + a DB helper to resolve the table(s). Never raises.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


async def resolve_source_tables(db, data_source_id: str) -> List[str]:
    """Active queryable table names for a data source (slugged DuckDB names)."""
    try:
        from sqlalchemy import select
        from app.models.datasource_table import DataSourceTable

        rows = (
            await db.execute(
                select(DataSourceTable.name).where(
                    DataSourceTable.datasource_id == str(data_source_id),
                    DataSourceTable.is_active.is_(True),
                )
            )
        ).scalars().all()
        return [r for r in rows if r]
    except Exception:  # noqa: BLE001
        logger.warning("golden_gen.resolve_source_tables failed", exc_info=True)
        return []


def from_clause(tables: List[str]) -> str:
    """Build the FROM target. One table -> `"t"`. Many same-schema -> a UNION ALL
    subquery aliased `src` (fallback when one-table-merge is off)."""
    if not tables:
        return ""
    if len(tables) == 1:
        return f'"{tables[0]}"'
    union = "\n  UNION ALL\n  ".join(f'SELECT * FROM "{t}"' for t in tables)
    return f"(\n  {union}\n) AS src"


def _ratio_expected(expected: List, scope: str) -> Optional[int]:
    """Pull the {scope: 'num'|'den'} ground-truth count out of a ratio def's
    `expected` list ([{"scope": "num", "value": 644}, ...]). None if absent."""
    try:
        for e in expected or []:
            if isinstance(e, dict) and e.get("scope") == scope:
                v = e.get("value")
                return int(v) if v is not None else None
    except Exception:  # noqa: BLE001
        pass
    return None


def _rate(num: Optional[int], den: Optional[int]) -> Optional[float]:
    """num/den as a percentage rounded to 2dp, or None when unknown/zero-den."""
    try:
        if num is None or not den:
            return None
        return round(100.0 * float(num) / float(den), 2)
    except Exception:  # noqa: BLE001
        return None


def build_count_sql(tables: List[str], predicate: str) -> Optional[str]:
    """`SELECT COUNT(*) AS value FROM <from> WHERE <predicate>`."""
    src = from_clause(tables)
    if not src or not (predicate or "").strip():
        return None
    return f"SELECT COUNT(*) AS value\nFROM {src}\nWHERE {predicate}"


async def generate_for_definitions(
    db, *, data_source_id: str, definitions: List,
) -> List[Dict]:
    """Build a golden candidate per definition. Returns
    [{definition_id, name, sql, expected}]. Never raises."""
    out: List[Dict] = []
    try:
        tables = await resolve_source_tables(db, data_source_id)
        if not tables:
            logger.warning("golden_gen: no active tables for ds %s", data_source_id)
            return out
        for d in definitions or []:
            pred = getattr(d, "sql_predicate", "") or ""
            if not pred.strip():
                continue
            sql = build_count_sql(tables, pred)
            if not sql:
                continue
            exp = None
            ex = getattr(d, "expected", None) or []
            if ex and isinstance(ex, list) and ex:
                exp = ex[0].get("value")
            cand = {
                "definition_id": str(getattr(d, "id", "")),
                "name": getattr(d, "name", "metric"),
                "sql": sql,
                "expected": exp,
            }
            # ratio metric (P8): sql_predicate is the NUMERATOR; also build den_sql.
            # `expected` for a ratio is {num, den} (and rate) so the eval gate can
            # verify BOTH counts. Flag-gated at the parse/registry side; here we just
            # honour a def already tagged kind='ratio' with a den_predicate.
            if str(getattr(d, "kind", "") or "") == "ratio":
                den_pred = getattr(d, "den_predicate", "") or ""
                den_sql = build_count_sql(tables, den_pred)
                if den_sql:
                    num_exp = _ratio_expected(ex, "num")
                    den_exp = _ratio_expected(ex, "den")
                    cand["metric_kind"] = "ratio"
                    cand["num_sql"] = sql
                    cand["den_sql"] = den_sql
                    cand["expected"] = {"num": num_exp, "den": den_exp,
                                        "rate": _rate(num_exp, den_exp)}
            out.append(cand)
    except Exception:  # noqa: BLE001
        logger.warning("golden_gen.generate_for_definitions failed", exc_info=True)
    return out
