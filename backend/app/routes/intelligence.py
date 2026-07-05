"""Intelligence layer data API (read-only).

Feeds the Studio → Intelligence rail (the 8 hybrid capability layers from
Wave 1+2). One endpoint, switch on `layer`. Org-scoped, fail-soft: any error
degrades to an empty table + note, never 500s the rail. Additive — no core
files touched beyond router registration. Toggles are NOT here: the rail
reuses the existing GET/PUT /api/organization/hybrid-flags endpoints.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.models.user import User
from app.models.organization import Organization
from app.models.studio import StudioDataSource
from app.models.datasource_table import DataSourceTable
from app.models.metric_definition import MetricDefinition
from app.models.query_library import QueryLibraryItem
from app.settings.hybrid_flags import flags as _flags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])

# layer -> (HYBRID_* env name, flags property name)
_LAYER_FLAG = {
    "profiler":   ("HYBRID_PROFILE_V2", "PROFILE_V2"),
    "codeenrich": ("HYBRID_CODE_ENRICH", "CODE_ENRICH"),
    "metrics":    ("HYBRID_VERIFIED_METRICS", "VERIFIED_METRICS"),
    "lazy":       ("HYBRID_PROFILE_V2", "PROFILE_V2"),
    "insights":   ("HYBRID_PROACTIVE_INSIGHTS", "PROACTIVE_INSIGHTS"),
    "forecast":   ("HYBRID_ADV_METHODS", "ADV_METHODS"),
    "golden":     ("HYBRID_GOLDEN_QUERIES", "GOLDEN_QUERIES"),
    "search":     ("HYBRID_SEMANTIC_SEARCH", "SEMANTIC_SEARCH"),
    "predictions": ("HYBRID_ADV_METHODS", "ADV_METHODS"),
}


async def _studio_ds_ids(db: AsyncSession, studio_id: str) -> list[str]:
    if not studio_id:
        return []
    try:
        res = await db.execute(
            select(StudioDataSource.agent_id).where(StudioDataSource.studio_id == studio_id)
        )
        return [r[0] for r in res.all() if r[0]]
    except Exception as e:  # noqa
        logger.warning("intelligence: studio sources lookup failed: %s", e)
        return []


async def _active_tables(db: AsyncSession, ds_ids: list[str]) -> list[DataSourceTable]:
    if not ds_ids:
        return []
    try:
        res = await db.execute(
            select(DataSourceTable).where(
                DataSourceTable.datasource_id.in_(ds_ids),
                DataSourceTable.is_active.is_(True),
            )
        )
        return list(res.scalars().all())
    except Exception as e:  # noqa
        logger.warning("intelligence: active tables lookup failed: %s", e)
        return []


def _empty(layer: str, env: str, enabled: bool, note: str) -> dict:
    return {"layer": layer, "flag": env, "enabled": enabled,
            "stats": None, "table": None, "note": note}


@router.get("/layer/{layer}")
async def get_layer(
    layer: str,
    studio_id: str = Query("", description="Studio id to scope data sources"),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict[str, Any]:
    """Return real data for one intelligence layer (read-only, fail-soft)."""
    if layer not in _LAYER_FLAG:
        return _empty(layer, "", False, "Unknown layer.")
    env, prop = _LAYER_FLAG[layer]
    enabled = bool(getattr(_flags, prop, False))
    org_id = organization.id

    try:
        ds_ids = await _studio_ds_ids(db, studio_id)

        # ---- PROFILER: profile_v2 catalog across the studio's tables ----
        if layer == "profiler":
            tables = await _active_tables(db, ds_ids)
            rows, n_cols, n_classified, n_variants = [], 0, 0, 0
            for tb in tables:
                meta = tb.metadata_json or {}
                prof = meta.get("profile_v2") if isinstance(meta, dict) else None
                if not isinstance(prof, dict):
                    continue
                for col, info in prof.items():
                    if not isinstance(info, dict):
                        continue
                    n_cols += 1
                    role = info.get("role", "")
                    if role:
                        n_classified += 1
                    tv = info.get("top_values") or []
                    top = " · ".join(
                        f"{t.get('value')} ({t.get('count')})" for t in tv[:3]
                        if isinstance(t, dict)
                    )
                    warn = info.get("variants_warning")
                    if warn:
                        n_variants += 1
                        top = (top + f"  ⚠ {warn}") if top else f"⚠ {warn}"
                    rows.append([f"{tb.name}.{col}", role or "—", top or "—"])
            if not rows:
                return _empty(layer, env, enabled,
                              "No profile_v2 yet. Enable Deep Profiler and run a train (or query) to populate.")
            pct = int(round(100 * n_classified / n_cols)) if n_cols else 0
            return {
                "layer": layer, "flag": env, "enabled": enabled,
                "stats": [
                    {"n": str(len(tables)), "l": "Tables"},
                    {"n": str(n_cols), "l": "Columns"},
                    {"n": f"{pct}%", "l": "Classified"},
                    {"n": str(n_variants), "l": "Variants"},
                ],
                "table": {"title": "Column catalog", "head": ["Column", "Role", "Top values"], "rows": rows},
                "note": None,
            }

        # ---- CODE ENRICH: pipeline_logic per table ----
        if layer == "codeenrich":
            tables = await _active_tables(db, ds_ids)
            rows = []
            for tb in tables:
                meta = tb.metadata_json or {}
                pl = meta.get("pipeline_logic") if isinstance(meta, dict) else None
                if not isinstance(pl, dict):
                    continue
                grain = pl.get("grain") or "—"
                src = pl.get("source") or pl.get("source_method") or "—"
                rows.append([tb.name, str(grain), str(src)])
            if not rows:
                return _empty(layer, env, enabled,
                              "No pipeline_logic yet. Enable Code Enrich and run a train to extract grain/formulas from source.")
            return {"layer": layer, "flag": env, "enabled": enabled, "stats": None,
                    "table": {"title": "Extracted pipeline logic", "head": ["Table", "Grain", "Source"], "rows": rows},
                    "note": None}

        # ---- VERIFIED METRICS ----
        if layer == "metrics":
            res = await db.execute(
                select(MetricDefinition).where(MetricDefinition.organization_id == org_id)
            )
            mets = list(res.scalars().all())
            rows = []
            for m in mets:
                locked = "LOCKED" if getattr(m, "is_locked", False) else "—"
                lv = getattr(m, "last_value", None)
                rows.append([m.name, locked, ("—" if lv is None else str(lv)), getattr(m, "status", "")])
            if not rows:
                return _empty(layer, env, enabled,
                              "No metrics defined. Add metrics in Knowledge → Metrics; lock one to make it authoritative.")
            n_locked = sum(1 for m in mets if getattr(m, "is_locked", False))
            return {"layer": layer, "flag": env, "enabled": enabled,
                    "stats": [{"n": str(len(mets)), "l": "Metrics"}, {"n": str(n_locked), "l": "Locked"}],
                    "table": {"title": "Metric library", "head": ["Metric", "Lock", "Last value", "Status"], "rows": rows},
                    "note": None}

        # ---- GOLDEN QUERIES ----
        if layer == "golden":
            res = await db.execute(
                select(QueryLibraryItem).where(QueryLibraryItem.organization_id == org_id)
            )
            qs = list(res.scalars().all())
            rows = []
            for q in qs:
                gold = "★ GOLDEN" if getattr(q, "is_golden", False) else (getattr(q, "status", "") or "—")
                rows.append([q.name, gold, str(getattr(q, "verified_count", 0)), str(getattr(q, "run_count", 0))])
            if not rows:
                return _empty(layer, env, enabled,
                              "No saved queries yet. Queries are captured from successful chats; thumbs-up or repeats promote them to golden.")
            n_gold = sum(1 for q in qs if getattr(q, "is_golden", False))
            return {"layer": layer, "flag": env, "enabled": enabled,
                    "stats": [{"n": str(len(qs)), "l": "Queries"}, {"n": str(n_gold), "l": "Golden"}],
                    "table": {"title": "Query library", "head": ["Question", "Status", "Verified", "Used"], "rows": rows},
                    "note": None}

        # ---- HYBRID SEARCH + KG (scaffold) ----
        if layer == "search":
            edges = []
            try:
                from app.models.brain_graph_edge import BrainGraphEdge  # local import, optional
                # NEWPIPE S4: build id->name lookup so edges render real names
                # (e.g. "Lead", "crm_conso") instead of "metric:fa75…"/"table:de3b…".
                name_of: dict[str, str] = {}
                try:
                    from app.models.semantic_table import SemanticTable
                    for m in (await db.execute(select(MetricDefinition).where(
                            MetricDefinition.organization_id == org_id))).scalars().all():
                        name_of[f"metric:{m.id}"] = m.name or f"metric:{str(m.id)[:8]}"
                    for t in (await db.execute(select(SemanticTable).where(
                            SemanticTable.organization_id == org_id))).scalars().all():
                        nm = getattr(t, "table_name", None) or getattr(t, "name", None) or ""
                        # strip dlt/physical "t_<32hex>_" prefix → readable label
                        import re as _re
                        nm = _re.sub(r"^t_([0-9a-f]{2,}_){1,6}", "", str(nm))
                        nm = _re.sub(r"_+", " ", nm).strip().title() or f"table:{str(t.id)[:8]}"
                        name_of[f"table:{t.id}"] = nm
                except Exception as le:  # noqa
                    logger.debug("intelligence: edge name lookup failed: %s", le)

                def _pretty(ent: str) -> str:
                    return name_of.get(ent, ent if ":" not in ent else ent.split(":")[0] + ":" + ent.split(":")[1][:8])

                res = await db.execute(
                    select(BrainGraphEdge).where(BrainGraphEdge.organization_id == org_id).limit(50)
                )
                for e in res.scalars().all():
                    edges.append([
                        _pretty(str(getattr(e, "src_entity", "?"))),
                        str(getattr(e, "relation", "related_to")),
                        _pretty(str(getattr(e, "dst_entity", "?"))),
                    ])
            except Exception as e:  # noqa
                logger.debug("intelligence: KG edges read failed: %s", e)
            note = "Scaffold — enable Hybrid Search to populate the index; prompt injection ships in a later wave."
            if not edges:
                return _empty(layer, env, enabled, note)
            return {"layer": layer, "flag": env, "enabled": enabled, "stats": None,
                    "table": {"title": "Knowledge graph edges", "head": ["From", "Relation", "To"], "rows": edges},
                    "note": note}

        # ---- transient layers: no persisted store ----
        if layer == "lazy":
            return _empty(layer, env, enabled,
                          "Lazy profiling runs at query time (cache-miss → inline profile). Activity isn't persisted; it shares the Deep Profiler flag + the LAZY_PROFILE_V2_DISABLED kill-switch.")
        if layer == "insights":
            return _empty(layer, env, enabled,
                          "Insights are computed per result and rendered as chips under the answer (z-score + IQR + spike). They are not stored on the agent.")
        if layer == "forecast":
            return _empty(layer, env, enabled,
                          "LLM forecasting — the agent reasons over your real monthly series (LLMTime, Claude reasoning, no statistical model) to project the next periods. Click Predict to run it live on this agent's Auto-EDA time series.")
        if layer == "predictions":
            return _empty(layer, env, enabled,
                          "LLM predictors — classify rows (TabLLM) and discover associations/segments (compute-then-narrate) over your real data. Run Find patterns to interpret this agent's computed correlations; classification is chat-driven on a live result.")

        return _empty(layer, env, enabled, "No data.")
    except Exception as e:  # noqa
        logger.warning("intelligence.get_layer(%s) failed: %s", layer, e)
        return _empty(layer, env, enabled, "Data temporarily unavailable.")


# ===========================================================================
# RUN framework (BI-uplift — make the Intelligence tabs LIVE, not static).
# Additive: get_layer above is untouched. Each tab's run-buttons are declared
# on the FE (StudioIntelligence.vue actionsFor()); this dispatches them here.
# Every handler is org-scoped + fail-soft; OFF flag → refuses cleanly.
# ===========================================================================

async def _load_primary_ds(db: AsyncSession, ds_ids: list[str]):
    """The studio's bound DataSource — prefer one that already has an Auto-EDA
    profile (needed by forecast/insights). None when the studio has no source."""
    if not ds_ids:
        return None
    try:
        from app.models.data_source import DataSource
        res = await db.execute(select(DataSource).where(DataSource.id.in_(ds_ids)))
        rows = list(res.scalars().all())
        for d in rows:
            if getattr(d, "eda_profile", None):
                return d
        return rows[0] if rows else None
    except Exception as e:  # noqa
        logger.warning("intelligence: primary ds load failed: %s", e)
        return None


def _eda_profile(ds) -> Optional[dict]:
    prof = getattr(ds, "eda_profile", None) if ds is not None else None
    if isinstance(prof, dict):
        p = prof.get("profile")
        return p if isinstance(p, dict) else None
    return None


# ---- P1 · Forecasting (LLM reasoning over the agent's real monthly series) --
async def _run_forecast(db, org, ds, params) -> dict:
    if ds is None:
        return {"ok": False, "note": "No data source is bound to this studio yet."}
    from app.services.analytics.agent_forecast import build_agent_forecast
    try:
        periods = int(params.get("periods") or 3)
    except Exception:
        periods = 3
    fc = await build_agent_forecast(db, organization=org, data_source=ds,
                                    periods=max(1, min(periods, 12)))
    if not fc.get("success"):
        return {"ok": False, "note": fc.get("message") or "No forecast available.",
                "disclaimer": fc.get("disclaimer")}
    rows = [[f["period"], f["yhat"], f"{f['yhat_lower']} – {f['yhat_upper']}", f["n_samples"]]
            for f in fc.get("forecast", [])]
    return {
        "ok": True,
        "stats": [
            {"n": (fc.get("direction") or "—").title(), "l": "Direction"},
            {"n": (fc.get("confidence") or "—").title(), "l": "Confidence"},
            {"n": str(fc.get("measure") or "value"), "l": "Measure"},
        ],
        "table": {"title": f"Forecast · {fc.get('measure','value')} (AI estimate)",
                  "head": ["Period", "Forecast", "Range (low – high)", "Samples"], "rows": rows},
        "text": fc.get("assumptions") or "",
        "model": fc.get("model"),
        "disclaimer": fc.get("disclaimer"),
    }


# ---- P2/P3 · Proactive Insights (compute-only scan of the Auto-EDA profile) -
def _insight_chips(p: dict) -> list[str]:
    chips: list[str] = []
    ts = p.get("time_series") or {}
    if isinstance(ts, dict) and ts.get("growth_pct") is not None:
        g = ts["growth_pct"]
        chips.append(f"{ts.get('measure','series')} moved {'+' if g >= 0 else ''}{round(g,1)}% over the period")
        if ts.get("peak_period"):
            chips.append(f"Peak {ts.get('measure','value')} in {ts['peak_period']} ({ts.get('peak_value')})")
    dist = p.get("distribution") or {}
    if isinstance(dist, dict) and dist.get("outlier_count"):
        chips.append(f"{dist['outlier_count']} outliers in {dist.get('column','a measure')} "
                     f"(outside {dist.get('outlier_low')}–{dist.get('outlier_high')})")
    for cp in (p.get("correlations") or [])[:3]:
        if isinstance(cp, dict):
            chips.append(f"{cp.get('a')} ↔ {cp.get('b')} {cp.get('direction','')} (r={cp.get('r')})")
    for c in (p.get("columns") or []):
        if isinstance(c, dict) and (c.get("null_pct") or 0) >= 20:
            chips.append(f"{c.get('name')} is {c.get('null_pct')}% empty — coverage gap")
    rk = p.get("ranking") or {}
    if isinstance(rk, dict) and rk.get("rows"):
        top = rk["rows"][0]
        chips.append(f"Top {rk.get('dim','item')} by {rk.get('measure','value')}: "
                     f"{top.get('label')} ({top.get('value')})")
    return chips[:8]


async def _run_insights(db, org, ds, params) -> dict:
    if ds is None:
        return {"ok": False, "note": "No data source is bound to this studio yet."}
    p = _eda_profile(ds)
    if not p:
        return {"ok": False, "note": "No Auto-EDA profile yet. Train this agent (Auto-EDA) first."}
    chips = _insight_chips(p)
    if not chips:
        return {"ok": True, "chips": [], "text": "No notable anomalies or trends in the current profile."}
    out = {"ok": True, "chips": chips, "text": f"{len(chips)} signals from the computed profile."}
    # optional AI narration (P8 cross-cut) — grounded ONLY on the chips above
    if params.get("explain"):
        from app.services.analytics import llm_predict as LP
        model = await LP.resolve_reason_model(db, org)
        prompt = ("You are a BI analyst. Below are computed signals from a dataset "
                  "profile (real numbers). Write 2-3 sentences: what a decision-maker "
                  "should notice and do. Use ONLY these signals; invent nothing.\n\n"
                  + "\n".join(f"- {c}" for c in chips))
        summary = await LP.infer(model, prompt, scope="intel_insights")
        if summary:
            out["text"] = summary
            out["disclaimer"] = LP.AI_ESTIMATE
    return out


# ---- P4 · Predictions hub · discover (LLM narrates real computed evidence) --
async def _run_discover(db, org, ds, params) -> dict:
    if ds is None:
        return {"ok": False, "note": "No data source is bound to this studio yet."}
    p = _eda_profile(ds)
    if not p:
        return {"ok": False, "note": "No Auto-EDA profile yet. Train this agent first."}
    from app.services.analytics import llm_predict as LP
    evidence: list[str] = []
    for cp in (p.get("correlations") or [])[:6]:
        if isinstance(cp, dict):
            evidence.append(f"corr {cp.get('a')}~{cp.get('b')} r={cp.get('r')} ({cp.get('direction')})")
    cs = p.get("category_shares") or {}
    for r in (cs.get("rows") or [])[:6]:
        evidence.append(f"{cs.get('dim')}={r.get('label')} share {r.get('pct')}% (n={r.get('count')})")
    rk = p.get("ranking") or {}
    for r in (rk.get("rows") or [])[:5]:
        evidence.append(f"{rk.get('dim')}={r.get('label')} {rk.get('measure')}={r.get('value')}")
    if not evidence:
        return {"ok": False, "note": "Not enough computed structure (correlations/segments) to interpret yet."}
    model = await LP.resolve_reason_model(db, org)
    prompt = ("You are a data-mining analyst. Below is REAL computed evidence "
              "(correlations, category shares, rankings) from a dataset. Surface up "
              "to 5 patterns a business would act on. Do NOT invent a pattern absent "
              "from the evidence. Return STRICT JSON only:\n"
              '{"findings":[{"pattern":"<short>","evidence":"<cite the numbers>",'
              '"strength":"high|med|low","action":"<one step>"}]}\n\n'
              "EVIDENCE:\n" + "\n".join(f"- {e}" for e in evidence))
    parsed = LP.extract_json(await LP.infer(model, prompt, scope="intel_discover")) or {}
    findings = parsed.get("findings") if isinstance(parsed.get("findings"), list) else []
    rows = [[f.get("pattern", "—"), f.get("evidence", "—"),
             str(f.get("strength", "")).title(), f.get("action", "—")]
            for f in findings if isinstance(f, dict)]
    if not rows:
        return {"ok": False, "note": "The model returned no usable patterns.",
                "disclaimer": LP.AI_ESTIMATE}
    return {"ok": True,
            "table": {"title": "Discovered patterns (AI estimate)",
                      "head": ["Pattern", "Evidence", "Strength", "Suggested action"], "rows": rows},
            "disclaimer": LP.AI_ESTIMATE}


# ---- P7 · Hybrid Search + KG · reindex / search ----------------------------
async def _run_reindex(db, org, ds, params) -> dict:
    try:
        from app.ai.knowledge.indexer import reindex_org
        res = await reindex_org(db, org)
        n = res.get("indexed") if isinstance(res, dict) else None
        return {"ok": True, "text": f"Reindexed knowledge — {n if n is not None else 'done'} items embedded."}
    except Exception as e:  # noqa
        logger.warning("intelligence: reindex failed: %s", e)
        return {"ok": False, "note": "Reindex failed."}


async def _run_search(db, org, ds, params) -> dict:
    q = str(params.get("query") or "").strip()
    if not q:
        return {"ok": False, "note": "Type something to search."}
    try:
        from app.ai.knowledge.hybrid_search import hybrid_search
        hits = await hybrid_search(db, org_id=org.id, query=q, k=8, organization=org)
        rows = [[h.get("kind", "—"), (h.get("title") or "")[:60],
                 (h.get("body") or "")[:80], round(float(h.get("score", 0) or 0), 3)]
                for h in (hits or [])]
        if not rows:
            return {"ok": True, "table": None, "text": f"No matches for “{q}”. Try Reindex first."}
        return {"ok": True, "table": {"title": f"Search · “{q}”",
                "head": ["Kind", "Title", "Snippet", "Score"], "rows": rows}}
    except Exception as e:  # noqa
        logger.warning("intelligence: search failed: %s", e)
        return {"ok": False, "note": "Search failed."}


_RUN_HANDLERS = {
    ("forecast", "run"):        _run_forecast,
    ("insights", "scan"):       _run_insights,
    ("predictions", "discover"): _run_discover,
    ("search", "reindex"):      _run_reindex,
    ("search", "search"):       _run_search,
}


@router.post("/layer/{layer}/run")
async def run_layer_action(
    layer: str,
    payload: dict = Body(default={}),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict[str, Any]:
    """Execute a run-action for an intelligence layer (org-scoped, fail-soft)."""
    action = str(payload.get("action") or "")
    studio_id = str(payload.get("studio_id") or "")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    env, prop = _LAYER_FLAG.get(layer, ("", ""))
    enabled = bool(getattr(_flags, prop, False)) if prop else False
    if not enabled:
        return {"ok": False, "note": "This capability is turned off — enable it above to run."}
    handler = _RUN_HANDLERS.get((layer, action))
    if handler is None:
        return {"ok": False, "note": "Unknown action."}
    try:
        ds_ids = await _studio_ds_ids(db, studio_id)
        ds = await _load_primary_ds(db, ds_ids)
        return await handler(db, organization, ds, params)
    except Exception as e:  # noqa
        logger.warning("intelligence.run(%s/%s) failed: %s", layer, action, e)
        return {"ok": False, "note": "Run failed — please retry."}
