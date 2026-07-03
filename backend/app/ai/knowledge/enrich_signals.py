"""CODE_ENRICH_PLUS signal helpers (flag ``HYBRID_CODE_ENRICH_PLUS``).

Three additive, fail-soft per-table facts that deepen ``code_enrich`` (which
already derives grain / formulas / population). Each function NEVER raises — on
any failure it returns an empty result and the caller simply skips that field:

  * ``derive_primary_keys``   — declared PK/UNIQUE (DDL / information_schema) or,
    for file/no-DDL sources, a column that is ~100% distinct + not-null
    (reuses the E3 column-profile in ``columns[].metadata`` / ``profile_v2``).
  * ``derive_downstream_usage`` — short list of the reports/dashboards/queries
    that consume this table (Query-Library sql mentions + dashboard-backed usage,
    reusing ``services/knowledge/usage_trust`` helpers).
  * ``derive_alternate_tables`` — when this table is stale/low-trust, name 1-2
    higher-trust sibling tables (join_miner ``table_edges`` neighbours ranked by
    the ``usage_trust`` score).

All output is small (capped) and JSON-serialisable so it can ride inside
``DataSourceTable.metadata_json['pipeline_logic']`` next to grain/formulas.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Caps keep the stored facts + the token cost bounded.
_MAX_PKS = 4
_MAX_CONSUMERS = 6
_MAX_ALTERNATES = 2
# Below this trust score a table is considered "stale/low-trust" → worth an
# alternate suggestion (trust is normalised to [0,1] by usage_trust).
_LOW_TRUST_CEIL = 0.5

# PRIMARY KEY (a, b) / UNIQUE (a) constraint bodies in a DDL string.
_PK_RE = re.compile(r'\bPRIMARY\s+KEY\s*\(([^)]+)\)', re.IGNORECASE)
_UNIQUE_RE = re.compile(r'\bUNIQUE\s*\(([^)]+)\)', re.IGNORECASE)
# Inline column-level `col ... PRIMARY KEY` — anchor on a column boundary (the
# opening paren or a comma) so the leading `CREATE TABLE` token is not captured.
_INLINE_PK_RE = re.compile(
    r'[(,]\s*("?[A-Za-z_][\w$]*"?)\b[^,]*?\bPRIMARY\s+KEY\b',
    re.IGNORECASE,
)


def _clean_col(tok: str) -> str:
    return (tok or "").strip().strip('"').strip('`').strip("[]").strip()


# ---------------------------------------------------------------------------
# 1) primary_keys
# ---------------------------------------------------------------------------

async def derive_primary_keys(
    *,
    tbl_row: Any,
    meta: Dict[str, Any],
    source_sql: Optional[str],
    client: Any,
    table_name: str,
) -> List[str]:
    """Best-effort primary-key columns. Empty list on any failure."""
    try:
        # (a) declared constraints in the source DDL / view SQL.
        pks = _pks_from_ddl(source_sql)
        if pks:
            return pks[:_MAX_PKS]

        # (b) declared PK from information_schema (SQL-backed base tables).
        if client is not None:
            pks = await _pks_from_information_schema(client, table_name)
            if pks:
                return pks[:_MAX_PKS]

        # (c) file/no-DDL fallback: a ~100% distinct, not-null column.
        pks = _pks_from_profile(tbl_row, meta)
        return pks[:_MAX_PKS]
    except Exception as e:
        logger.debug("enrich_signals.derive_primary_keys(%s): %s", table_name, e)
        return []


def _pks_from_ddl(source_sql: Optional[str]) -> List[str]:
    if not source_sql:
        return []
    out: List[str] = []
    m = _PK_RE.search(source_sql)
    if m:
        out.extend(_clean_col(c) for c in m.group(1).split(","))
    if not out:
        for im in _INLINE_PK_RE.finditer(source_sql):
            out.append(_clean_col(im.group(1)))
    if not out:
        um = _UNIQUE_RE.search(source_sql)
        if um:
            out.extend(_clean_col(c) for c in um.group(1).split(","))
    # De-dup, drop empties, preserve order.
    seen: set = set()
    return [c for c in out if c and not (c.lower() in seen or seen.add(c.lower()))]


async def _pks_from_information_schema(client: Any, table_name: str) -> List[str]:
    """Read the declared PRIMARY KEY columns from information_schema (PG)."""
    try:
        sql = (
            "SELECT kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            " AND tc.table_schema = kcu.table_schema "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            f"  AND tc.table_name = '{table_name}' "
            "ORDER BY kcu.ordinal_position"
        )
        df = await asyncio.to_thread(client.execute_query, sql)
        if df is not None and not df.empty:
            return [_clean_col(str(v)) for v in df.iloc[:, 0].tolist() if v]
    except Exception as e:
        logger.debug("enrich_signals: info_schema PK for %s: %s", table_name, e)
    return []


def _pks_from_profile(tbl_row: Any, meta: Dict[str, Any]) -> List[str]:
    """A column that is ~100% distinct and not-null looks like a natural key.

    Prefers the E3 column-profile stored in ``columns[].metadata``
    (``distinct`` / ``null_pct``) against ``no_rows``; falls back to the
    ``profile_v2`` IDENTIFIER role classification.
    """
    # (c1) column-profile uniqueness.
    try:
        no_rows = int(getattr(tbl_row, "no_rows", 0) or 0)
        cols = getattr(tbl_row, "columns", None)
        if no_rows > 1 and isinstance(cols, list):
            hits: List[str] = []
            for entry in cols:
                if not isinstance(entry, dict):
                    continue
                cmeta = entry.get("metadata")
                if not isinstance(cmeta, dict):
                    continue
                distinct = cmeta.get("distinct")
                null_pct = cmeta.get("null_pct")
                name = entry.get("name")
                if (
                    name
                    and isinstance(distinct, (int, float))
                    and distinct >= 0.99 * no_rows
                    and (null_pct in (0, 0.0, None))
                ):
                    hits.append(str(name))
            if hits:
                return hits
    except Exception as e:
        logger.debug("enrich_signals: column-profile PK fallback: %s", e)

    # (c2) profile_v2 IDENTIFIER roles.
    try:
        profile = meta.get("profile_v2")
        if isinstance(profile, dict):
            return [
                c for c, info in profile.items()
                if isinstance(info, dict) and info.get("role") == "IDENTIFIER"
            ]
    except Exception as e:
        logger.debug("enrich_signals: profile_v2 PK fallback: %s", e)
    return []


# ---------------------------------------------------------------------------
# 2) downstream_usage
# ---------------------------------------------------------------------------

async def derive_downstream_usage(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    table_name: str,
) -> List[str]:
    """Short list of consumers: saved queries + dashboard-backed report count."""
    out: List[str] = []
    try:
        from app.services.knowledge.usage_trust import _name_in_sql

        low = (table_name or "").lower()
        if not low:
            return []

        # (a) Query-Library items whose SQL references this table.
        try:
            from sqlalchemy import select
            from app.models.query_library import QueryLibraryItem

            q = select(QueryLibraryItem).where(
                QueryLibraryItem.organization_id == organization_id
            )
            if data_source_id:
                q = q.where(QueryLibraryItem.data_source_id == data_source_id)
            res = await db.execute(q)
            for it in res.scalars().all():
                sql = (getattr(it, "sql_text", "") or "").lower()
                if sql and _name_in_sql(low, sql):
                    label = getattr(it, "name", None) or "unnamed"
                    tag = "golden" if getattr(it, "is_golden", False) else "query"
                    out.append(f"{tag}: {label}")
                    if len(out) >= _MAX_CONSUMERS:
                        break
        except Exception as e:
            logger.debug("enrich_signals: query-library usage: %s", e)

        # (b) dashboard-backed report count (reuse usage_trust helper).
        if len(out) < _MAX_CONSUMERS:
            try:
                from app.services.knowledge.usage_trust import _dashboard_trust

                dash = await _dashboard_trust(
                    db, organization_id, data_source_id, [table_name]
                )
                cnt = int(dash.get(table_name, 0) or 0)
                if cnt > 0:
                    out.append(f"{cnt} dashboard-backed report(s)")
            except Exception as e:
                logger.debug("enrich_signals: dashboard usage: %s", e)
    except Exception as e:
        logger.debug("enrich_signals.derive_downstream_usage(%s): %s", table_name, e)
        return []
    return out[:_MAX_CONSUMERS]


# ---------------------------------------------------------------------------
# 3) alternate_tables
# ---------------------------------------------------------------------------

async def derive_alternate_tables(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    table_name: str,
) -> List[Dict[str, Any]]:
    """When this table is low-trust, name 1-2 higher-trust joined siblings."""
    try:
        from app.services.knowledge.usage_trust import table_trust_scores

        scores = await table_trust_scores(
            db, organization_id=organization_id, data_source_id=data_source_id
        )
        if not scores:  # flag OFF or no trust signal → nothing to suggest.
            return []

        low = (table_name or "").lower()
        self_trust = float(scores.get(low, 0.0) or 0.0)
        # Only surface an alternate for a genuinely stale/low-trust table.
        if self_trust >= _LOW_TRUST_CEIL:
            return []

        neighbours = await _edge_neighbours(
            db, organization_id, data_source_id, low
        )
        if not neighbours:
            return []

        ranked = sorted(
            (
                {"table": n, "trust": round(float(scores.get(n, 0.0) or 0.0), 4)}
                for n in neighbours
                if float(scores.get(n, 0.0) or 0.0) > self_trust
            ),
            key=lambda r: r["trust"],
            reverse=True,
        )
        for r in ranked:
            r["reason"] = (
                f"higher-trust sibling ({r['trust']}) joined to "
                f"{table_name} (this table trust {round(self_trust, 4)})"
            )
        return ranked[:_MAX_ALTERNATES]
    except Exception as e:
        logger.debug("enrich_signals.derive_alternate_tables(%s): %s", table_name, e)
        return []


async def _edge_neighbours(
    db: Any, organization_id: str, data_source_id: Optional[str], low_name: str
) -> List[str]:
    """Approved join-graph neighbours of ``low_name`` (edges store lowercased)."""
    try:
        from sqlalchemy import select, or_
        from app.models.table_edge import TableEdge

        q = select(TableEdge).where(
            TableEdge.organization_id == organization_id,
            TableEdge.status == "approved",
            or_(
                TableEdge.left_table == low_name,
                TableEdge.right_table == low_name,
            ),
        )
        if data_source_id:
            q = q.where(TableEdge.data_source_id == data_source_id)
        res = await db.execute(q)
        out: List[str] = []
        for e in res.scalars().all():
            other = e.right_table if e.left_table == low_name else e.left_table
            if other and other != low_name and other not in out:
                out.append(other)
        return out
    except Exception as e:
        logger.debug("enrich_signals._edge_neighbours(%s): %s", low_name, e)
        return []
