"""Per-agent KPI layer (BI-uplift Phase 3, flag HYBRID_KPI_LAYER).

Governs each agent's KPIs the way the deck's KPI series prescribes:
  * prefer OUTCOME ratios over ACTIVITY counts,
  * classify each KPI leading vs lagging + its dependency parent,
  * carry target / owner / action-on-breach.

Compute-then-narrate: the agent's computed EDA profile (real columns + shares +
time series) is the grounding; the LLM proposes governed KPIs from it (never
inventing columns). Persisted to ``data_sources.kpi_defs``. One set per agent,
overwritten on retrain / on demand. Rendered on the agent Overview only.

Fail-soft: returns ``{"error": ...}`` and never raises into a train run.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import update

from app.models.data_source import DataSource
from app.services.analytics import compute

logger = logging.getLogger(__name__)

KPI_VERSION = 1
_MAX_KPIS = 6


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


async def _profile_for(db, organization, data_source) -> Optional[dict]:
    """Reuse the agent's stored EDA profile; else compute a fresh one."""
    prof = None
    try:
        raw = getattr(data_source, "eda_profile", None)
        if isinstance(raw, dict) and raw.get("profile"):
            prof = raw["profile"]
    except Exception:
        prof = None
    if prof:
        return prof
    # fall back to a fresh sample+profile via the EDA loader
    try:
        from app.services.analytics.agent_eda import _load_sample_sync
        from app.models.datasource_table import DataSourceTable
        from sqlalchemy import select
        rows = list((await db.execute(
            select(DataSourceTable)
            .where(DataSourceTable.datasource_id == str(data_source.id))
            .where(DataSourceTable.is_active.is_(True))
        )).scalars().all())
        if not rows:
            return None
        df, _ = await asyncio.to_thread(
            _load_sample_sync, rows[0], str(getattr(organization, "id", "")))
        if df is None or len(df) == 0:
            return None
        return compute.profile_dataframe(df, table_name=getattr(rows[0], "name", ""))
    except Exception as e:  # noqa: BLE001
        logger.debug("agent_kpis profile fallback failed: %s", e)
        return None


def _prompt(agent_name: str, profile: dict) -> str:
    cols = [{"name": c["name"], "role": c["role"]} for c in profile.get("columns", [])][:30]
    slim = {
        "columns": cols,
        "category_shares": profile.get("category_shares"),
        "time_series": {k: profile.get("time_series", {}).get(k)
                        for k in ("measure", "peak_period", "growth_pct")} if profile.get("time_series") else None,
        "ranking": profile.get("ranking"),
    }
    return (
        "You are a business analytics lead defining the KEY metrics (KPIs) for an "
        f"agent named '{agent_name}', from its real data profile below.\n\n"
        f"DATA PROFILE (real columns only):\n{json.dumps(slim, default=str)}\n\n"
        "Define 3-6 KPIs. RULES:\n"
        "- Prefer OUTCOME ratios (conversion rate, success rate, revenue per X) over "
        "raw ACTIVITY counts. If only a count is possible, set kind='activity' and put "
        "a better outcome ratio in 'better'.\n"
        "- Each KPI must be computable from the REAL columns above — never invent columns.\n"
        "- Classify 'leading' (predicts, moves first) or 'lagging' (final result).\n"
        "- 'depends_on' = the name of the upstream KPI this one leads to, or \"\".\n"
        "- Give a plain 'definition', a 'kind' ('outcome'|'activity'), a 'cadence' "
        "('daily'|'weekly'|'monthly'), and an 'action' to take if it breaches.\n"
        "- 'target' may be an empty string if unknown.\n\n"
        "Return STRICT JSON only, no prose, no code fences:\n"
        '{"kpis":[{"name":"","definition":"","kind":"outcome","better":"",'
        '"leading_lagging":"lagging","depends_on":"","cadence":"monthly",'
        '"target":"","action":""}]}'
    )


def _clean_kpis(parsed: dict, real_cols: set) -> list[dict]:
    out = []
    for k in (parsed.get("kpis") or [])[:_MAX_KPIS]:
        if not isinstance(k, dict):
            continue
        name = str(k.get("name", "")).strip()
        definition = str(k.get("definition", "")).strip()
        if not name or not definition:
            continue
        kind = str(k.get("kind", "")).strip().lower()
        if kind not in ("outcome", "activity"):
            kind = "outcome"
        ll = str(k.get("leading_lagging", "")).strip().lower()
        if ll not in ("leading", "lagging"):
            ll = "lagging"
        # grounding: definition should reference at least one real column token
        text_l = (name + " " + definition).lower()
        grounded = any(str(c).lower() in text_l for c in real_cols) if real_cols else True
        out.append({
            "name": name[:80],
            "definition": definition[:240],
            "kind": kind,
            "better": str(k.get("better", "")).strip()[:120],
            "leading_lagging": ll,
            "depends_on": str(k.get("depends_on", "")).strip()[:80],
            "cadence": str(k.get("cadence", "monthly")).strip().lower()[:12] or "monthly",
            "target": str(k.get("target", "")).strip()[:60],
            "owner": None,
            "action": str(k.get("action", "")).strip()[:200],
            "grounded": bool(grounded),
        })
    return out


async def build_agent_kpis(db, *, organization, data_source, model=None,
                           llm_inference=None) -> dict:
    """Build + persist governed KPI definitions for one agent. Returns the
    payload or ``{"error": ...}``. Fail-soft; never raises."""
    try:
        ds_id = str(data_source.id)
        agent_name = getattr(data_source, "name", "") or "this agent"

        profile = await _profile_for(db, organization, data_source)
        if not profile or not profile.get("columns"):
            return {"error": "no profile/columns"}

        real_cols = {c.get("name") for c in profile.get("columns", []) if c.get("name")}

        infer = llm_inference
        if infer is None and model is not None:
            def infer(p: str) -> str:  # noqa: E306
                from app.ai.llm.llm import LLM
                from app.dependencies import async_session_maker
                return LLM(model, usage_session_maker=async_session_maker).inference(
                    p, usage_scope="agent_kpis")
        if infer is None:
            return {"error": "no model"}

        raw = await asyncio.to_thread(infer, _prompt(agent_name, profile))
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            return {"error": "unparseable KPI proposal"}

        kpis = _clean_kpis(parsed, real_cols)
        if not kpis:
            return {"error": "no valid KPIs"}

        payload = {
            "version": KPI_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kpis": kpis,
        }
        try:
            await db.execute(update(DataSource).where(DataSource.id == ds_id)
                             .values(kpi_defs=payload))
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
