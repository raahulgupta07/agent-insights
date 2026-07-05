"""Per-agent Auto-EDA (BI-uplift Phase 6, flag HYBRID_AUTO_EDA).

For ONE agent (= data_source), load a bounded data sample, compute the profile
deterministically (compute.py), optionally narrate it with the LLM (insights +
suggested first questions — grounded ONLY on the computed numbers, never invents
figures), fold in the data-prep summary (Phase 5), and persist the whole thing
to ``data_sources.eda_profile``. One profile per agent, overwritten on retrain.
Rendered solely on that agent's Overview.

Compute-then-narrate + fail-soft: any failure returns ``{"error": ...}`` and
never raises into the train run. Data loading reuses profile_v2's proven
physical-table resolver so it works across staging/warehouse layouts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update, text

from app.models.data_source import DataSource
from app.models.datasource_table import DataSourceTable
from app.services.analytics import compute

logger = logging.getLogger(__name__)

_SAMPLE_ROWS = 5000
EDA_VERSION = 1


# --- data loading (reuse profile_v2 resolver) ------------------------------

def _org_staging_schema(organization_id: str) -> str:
    """Per-org staging schema the loader writes into: 'staging_' + first 16 hex
    of the org id (dashes stripped). Matches services.ingest.tenant_schema."""
    hexid = str(organization_id or "").replace("-", "")[:16]
    return f"staging_{hexid}"


def _resolve_physical_fallback(engine, table_row, organization_id) -> Any:
    """When profile_v2's resolver misses (null ConnectionTable schema / truncated
    physical name), locate the table by prefix-match inside the org staging schema.
    The ConnectionTable name carries a unique uuid prefix, so a LIKE '<name>%' is
    unambiguous. Returns (schema, name) or None."""
    try:
        base = getattr(table_row, "name", None)
        if not base:
            return None
        schema = _org_staging_schema(organization_id)
        like = base[:50] + "%"
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name LIKE :l "
                    "ORDER BY length(table_name) ASC LIMIT 1"
                ),
                {"s": schema, "l": like},
            ).first()
            if row:
                return (schema, row[0])
            # last resort: any staging_* schema with the prefix
            row = conn.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema LIKE 'staging\\_%' AND table_name LIKE :l "
                    "ORDER BY length(table_name) ASC LIMIT 1"
                ),
                {"l": like},
            ).first()
            if row:
                return (row[0], row[1])
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug("agent_eda _resolve_physical_fallback failed: %s", e)
        return None


def _load_sample_sync(table_row, organization_id: str = "") -> Any:
    """Blocking: resolve the physical table and SELECT a bounded sample into a
    pandas DataFrame. Returns (df, physical_name) or (None, None). Never raises."""
    try:
        import pandas as pd
        from app.ai.knowledge.profile_v2 import _loader_engine, _resolve_physical
        engine = _loader_engine()
        resolved = _resolve_physical(engine, table_row)
        if not resolved:
            resolved = _resolve_physical_fallback(engine, table_row, organization_id)
        if not resolved:
            return None, None
        schema, name = resolved
        q = text(f'SELECT * FROM "{schema}"."{name}" LIMIT {_SAMPLE_ROWS}')
        with engine.connect() as conn:
            df = pd.read_sql(q, conn)
        return df, f"{schema}.{name}"
    except Exception as e:  # noqa: BLE001
        logger.debug("agent_eda _load_sample_sync failed: %s", e)
        return None, None


# --- LLM narration ----------------------------------------------------------

def _extract_json(text_in: str) -> Optional[dict]:
    if not text_in:
        return None
    for candidate in (text_in, re.sub(r"^```(?:json)?|```$", "", text_in.strip(), flags=re.M)):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    m = re.search(r"\{.*\}", text_in, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _narration_prompt(agent_name: str, profile: dict, prep: dict) -> str:
    """Compact prompt built ONLY from computed aggregates (no raw rows)."""
    slim = {
        "rows": profile.get("n_rows"), "cols": profile.get("n_cols"),
        "columns": [{"name": c["name"], "role": c["role"]} for c in profile.get("columns", [])][:20],
        "category_shares": profile.get("category_shares"),
        "time_series": {k: profile.get("time_series", {}).get(k)
                        for k in ("measure", "peak_period", "growth_pct")} if profile.get("time_series") else None,
        "ranking": profile.get("ranking"),
        "distribution": {k: profile.get("distribution", {}).get(k)
                         for k in ("column", "median", "outlier_count")} if profile.get("distribution") else None,
        "correlations": profile.get("correlations"),
        "rows_dropped": prep.get("rows_droppable"),
    }
    return (
        "You are a senior data analyst. Below is a COMPUTED profile of one dataset "
        f"for the agent '{agent_name}'. Using ONLY these numbers (never invent figures), "
        "write a brief first-look.\n\n"
        f"PROFILE:\n{json.dumps(slim, default=str)}\n\n"
        "Return STRICT JSON only, no prose, no code fences:\n"
        '{"insights": ["<=5 short factual insight strings grounded in the numbers"], '
        '"suggested_questions": ["4 specific first questions a user could ask this agent"]}'
    )


def _fallback_narration(profile: dict) -> dict:
    ins, qs = [], []
    cs = profile.get("category_shares")
    if cs and cs.get("rows"):
        top = cs["rows"][0]
        ins.append(f"{top['label']} leads {cs['dim']} at {top['pct']}% of the total.")
        qs.append(f"How is {cs['dim']} trending over time?")
    ts = profile.get("time_series")
    if ts:
        if ts.get("peak_period"):
            ins.append(f"{ts.get('measure','value')} peaks in {ts['peak_period']}.")
            qs.append(f"Why did {ts.get('measure','value')} change after {ts['peak_period']}?")
        if ts.get("growth_pct") is not None:
            ins.append(f"{ts.get('measure','value')} moved {ts['growth_pct']}% overall.")
    rk = profile.get("ranking")
    if rk and rk.get("rows"):
        ins.append(f"Top {rk['dim']}: {rk['rows'][0]['label']} by {rk['measure']}.")
        qs.append(f"What drives the top {rk['dim']} by {rk['measure']}?")
    dist = profile.get("distribution")
    if dist and dist.get("outlier_count"):
        ins.append(f"{dist['outlier_count']} outliers detected in {dist['column']}.")
    if not qs:
        qs = ["Summarise this dataset.", "What changed most recently?",
              "Show the top categories.", "Are there any anomalies?"]
    return {"insights": ins[:5], "suggested_questions": qs[:4]}


# --- public entry -----------------------------------------------------------

async def build_agent_eda(db, *, organization, data_source, model=None,
                          llm_inference=None) -> dict:
    """Build + persist the EDA profile for one agent. Returns the payload or
    ``{"error": ...}``. Fail-soft; never raises."""
    try:
        ds_id = str(data_source.id)
        agent_name = getattr(data_source, "name", "") or "this agent"

        # 1. primary active table
        try:
            tbl_rows = list((await db.execute(
                select(DataSourceTable)
                .where(DataSourceTable.datasource_id == ds_id)
                .where(DataSourceTable.is_active.is_(True))
            )).scalars().all())
        except Exception as e:  # noqa: BLE001
            return {"error": f"no tables: {e}"}
        if not tbl_rows:
            return {"error": "no active tables"}
        table_row = tbl_rows[0]

        # 2. load a bounded sample off-thread (sync engine)
        df, physical = await asyncio.to_thread(
            _load_sample_sync, table_row, str(getattr(organization, "id", "")))
        if df is None or len(df) == 0:
            return {"error": "no data sample"}

        # 3. compute (deterministic)
        profile = compute.profile_dataframe(df, table_name=getattr(table_row, "name", physical or ""))
        prep = compute.missing_data_plan(df)

        # 4. narrate (LLM, grounded on computed profile only) — off-thread, fail-soft
        narration = None
        try:
            infer = llm_inference
            if infer is None and model is not None:
                def infer(p: str) -> str:  # noqa: E306
                    from app.ai.llm.llm import LLM
                    from app.dependencies import async_session_maker
                    return LLM(model, usage_session_maker=async_session_maker).inference(
                        p, usage_scope="agent_eda")
            if infer is not None:
                raw = await asyncio.to_thread(infer, _narration_prompt(agent_name, profile, prep))
                narration = _extract_json(raw)
        except Exception as e:  # noqa: BLE001
            logger.debug("agent_eda narration failed for %s: %s", ds_id, e)
        if not isinstance(narration, dict) or not narration.get("insights"):
            narration = _fallback_narration(profile)

        # 5. assemble + persist
        payload = {
            "version": EDA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "table": physical or getattr(table_row, "name", ""),
            "n_tables": len(tbl_rows),
            "profile": profile,
            "prep": prep,
            "insights": narration.get("insights", []),
            "suggested_questions": narration.get("suggested_questions", []),
        }
        try:
            await db.execute(update(DataSource).where(DataSource.id == ds_id)
                             .values(eda_profile=payload))
            await db.commit()
        except Exception as e:  # noqa: BLE001
            try:
                await db.rollback()
            except Exception:
                pass
            return {"error": f"persist failed: {e}"}

        return payload
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
