"""Learn-from-data sampler (flag HYBRID_LEARN_FROM_DATA, default OFF).

Upstream bagofwords onboards a data source from SCHEMA STRUCTURE ONLY (table +
column names, dtypes, PK/FK, descriptions). That is enough when the source has
real foreign keys and column comments. Power BI (User Sign-in) connectors have
NONE of that — no FKs, no column descriptions — so the onboarding LLM had only
bare names to go on and hallucinated a whole domain from the connector's display
name ("User Sign-in" → invented @SignInLogs).

This module goes one step BEYOND upstream: at learn time it pulls a tiny sample
of REAL rows from each active table and records a few example values per column
into `DataSourceTable.columns[i]["metadata"]["values"]`. The schema renderer
(`tables_schema_section`) already surfaces that as `values="..."`, so the
generators now see actual data (e.g. `tier = [Gold, Silver]`,
`amount = [1200, 450]`) and can describe the true domain — and physically cannot
invent tables/columns that aren't there.

Design rules:
- Fail-soft everywhere: any error samples nothing, leaves the table untouched.
- Bounded: N rows/table, small per-column value cap, hard per-table timeout,
  abort the whole pass on a 429 (Power BI rate limit).
- PII-safe: columns whose name looks like sensitive identity data are NEVER
  sampled into the prompt/DB — only their presence is known, not their values.
- Idempotent: re-running overwrites the `values` metadata, never duplicates.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)

# Don't put these values in a prompt or the DB — sample presence only.
_PII_COL = re.compile(
    r"passport|identity|identific|\bnric\b|\bnrc\b|national.?id|\bssn\b|"
    r"birth|dob|date.?of.?birth|phone|mobile|email|address|tax.?id|account.?number",
    re.I,
)

_SAMPLE_ROWS = 8          # rows pulled per table
_MAX_VALUES = 6           # distinct example values kept per column
_MAX_VAL_LEN = 60         # truncate long values
_MAX_TABLES = 40          # safety cap on tables sampled per sync
_PER_TABLE_TIMEOUT = 10.0  # seconds


def _is_pbi(client: Any, conn_type: str) -> bool:
    name = (type(client).__name__ or "").lower()
    return "powerbi" in name or "powerbi" in (conn_type or "").lower()


def _clean_value(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    if len(s) > _MAX_VAL_LEN:
        s = s[: _MAX_VAL_LEN - 1] + "…"
    return s


def _strip_bracket(col: str) -> str:
    """Power BI returns columns as `Table[col]` (and sometimes `Table[col` with the
    trailing bracket dropped by pandas) — reduce either to `col`."""
    s = str(col)
    if "[" in s:
        s = s.split("[", 1)[1]
    return s.rstrip("]").strip()


def _sample_df_for_pbi(client: Any, full_name: str):
    """Run EVALUATE TOPN and return a DataFrame (or None). Raises on 429 so the
    caller can abort the whole pass."""
    model_tbl = full_name.split("/")[-1]
    dax = f"EVALUATE TOPN({_SAMPLE_ROWS}, '{model_tbl}')"
    return client.execute_query(dax, table_name=full_name, max_rows=_SAMPLE_ROWS)


def _profile_from_df(df, columns: list[dict]) -> dict[str, list[str]]:
    """Map DataFrame → {column_name: [example values]} keyed to the stored column
    names, skipping PII columns."""
    if df is None or getattr(df, "empty", True):
        return {}
    # normalized df column name → original df column
    df_map: dict[str, str] = {}
    for raw in df.columns:
        df_map[_strip_bracket(str(raw)).strip().lower()] = raw

    out: dict[str, list[str]] = {}
    for col in columns:
        cname = (col.get("name") or "").strip()
        if not cname or _PII_COL.search(cname):
            continue
        raw = df_map.get(cname.lower())
        if raw is None:
            continue
        vals: list[str] = []
        seen: set[str] = set()
        for v in df[raw].tolist():
            cv = _clean_value(v)
            if cv is None or cv in seen:
                continue
            seen.add(cv)
            vals.append(cv)
            if len(vals) >= _MAX_VALUES:
                break
        if vals:
            out[cname] = vals
    return out


async def sample_active_tables(
    db,
    client: Any,
    data_source,
    conn_type: str = "",
) -> int:
    """Sample real rows for every ACTIVE table of `data_source` and record example
    values into each column's metadata. Returns the number of tables enriched.

    Only Power BI is wired today (the connector that needed it); other client
    types no-op cleanly until a sampler is added for them.
    """
    from app.models.datasource_table import DataSourceTable

    if not _is_pbi(client, conn_type):
        return 0

    rows = (
        await db.execute(
            select(DataSourceTable).where(
                DataSourceTable.datasource_id == str(data_source.id),
                DataSourceTable.is_active == True,  # noqa: E712
            )
        )
    ).scalars().all()

    enriched = 0
    aborted = False
    for t in rows[:_MAX_TABLES]:
        if aborted:
            break
        cols = t.columns or []
        if not cols:
            continue
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(_sample_df_for_pbi, client, t.name),
                timeout=_PER_TABLE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.info("connector_sampler: timeout sampling %s", t.name)
            continue
        except Exception as e:
            if "429" in str(e):
                logger.warning("connector_sampler: 429 — aborting sample pass")
                aborted = True
            continue

        examples = _profile_from_df(df, cols)
        if not examples:
            continue

        changed = False
        for col in cols:
            cname = col.get("name")
            if cname in examples:
                meta = dict(col.get("metadata") or {})
                meta["values"] = examples[cname]
                meta["values_source"] = "sample"
                col["metadata"] = meta
                changed = True
        if changed:
            t.columns = cols
            flag_modified(t, "columns")
            db.add(t)
            enriched += 1

    if enriched:
        await db.commit()
    return enriched
