"""agent_forecast — per-agent LLM forecast for the Agent Overview (BI-uplift P7).

Forecasts the agent's primary time series (the one Auto-EDA already computed)
by LLM reasoning — LLMTime, no statistical model. Transient (recomputed on
demand, no DB column). Gated by HYBRID_ADV_METHODS. Pins a Claude reasoning
model when the org has one enabled, else falls back to the reasoning tier.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def _resolve_claude_reason_model(db, organization, fallback=None):
    """Prefer an enabled Claude model (user asked to pin Claude reasoning);
    else the org's reasoning tier via llm_predict. Never raises."""
    try:
        from sqlalchemy import select
        from app.models.llm_model import LLMModel
        rows = list((await db.execute(
            select(LLMModel).where(
                LLMModel.organization_id == organization.id,
                LLMModel.is_enabled == True,  # noqa: E712
            )
        )).scalars().all())
        claude = [m for m in rows if "claude" in str(getattr(m, "model_id", "")).lower()
                  or "claude" in str(getattr(m, "name", "")).lower()]
        if claude:
            # prefer opus/sonnet (reasoning) over haiku
            claude.sort(key=lambda m: (
                0 if "opus" in str(getattr(m, "model_id", "")).lower() else
                1 if "sonnet" in str(getattr(m, "model_id", "")).lower() else 2))
            return claude[0]
    except Exception as e:  # noqa: BLE001
        logger.debug("_resolve_claude_reason_model failed: %s", e)
    from app.services.analytics import llm_predict as LP
    return await LP.resolve_reason_model(db, organization, fallback=fallback)


def _history_points(data_source) -> tuple[list[dict], str]:
    """Real (period, value) history from the agent's Auto-EDA time series."""
    prof = getattr(data_source, "eda_profile", None) or {}
    ts = ((prof.get("profile") or {}).get("time_series")) if isinstance(prof, dict) else None
    if isinstance(ts, dict) and isinstance(ts.get("points"), list):
        pts = [{"period": str(p.get("period")), "value": p.get("value")}
               for p in ts["points"] if p.get("value") is not None]
        return pts, str(ts.get("measure") or "value")
    return [], "value"


async def build_agent_forecast(db, *, organization, data_source, model=None, periods: int = 3) -> dict:
    """Forecast the agent's primary series. Returns a JSON-safe dict; fail-soft."""
    from app.services.analytics import llm_predict as LP

    history, measure = _history_points(data_source)
    if len(history) < 3:
        return {"success": False, "reason": "no_series",
                "message": "This agent has no monthly time series to forecast yet. "
                           "Run Auto-EDA first.", "disclaimer": LP.AI_ESTIMATE}

    history = history[-60:]
    rmodel = await _resolve_claude_reason_model(db, organization, fallback=model)
    series_txt = "\n".join(f"{p['period']}: {p['value']}" for p in history)
    prompt = (
        "You are a forecasting analyst. Below is a real historical monthly series "
        f"of '{measure}'. Extrapolate the NEXT {periods} months by reasoning about "
        "level, trend, and any repeating seasonality. Do NOT just repeat the last "
        "value; think step by step, then answer.\n\n"
        f"SERIES (oldest to newest):\n{series_txt}\n\n"
        "Return STRICT JSON only, no prose, no code fences:\n"
        '{"forecast":[{"period":"<label>","value":<number>}],'
        '"assumptions":"<one sentence>","direction":"up|down|flat",'
        '"confidence":"high|med|low"}'
    )

    samples = await LP.infer_samples(rmodel, prompt, n=3, scope="agent_forecast")
    parsed = [p for p in (LP.extract_json(s) for s in samples) if isinstance(p, dict)]
    if not parsed:
        return {"success": False, "reason": "no_forecast",
                "message": "The model did not return a usable forecast.",
                "disclaimer": LP.AI_ESTIMATE}

    horizons: list[list[float]] = [[] for _ in range(periods)]
    labels: list[str] = ["" for _ in range(periods)]
    for pj in parsed:
        fc = pj.get("forecast") if isinstance(pj.get("forecast"), list) else []
        for i, row in enumerate(fc[:periods]):
            if not isinstance(row, dict):
                continue
            try:
                horizons[i].append(float(row.get("value")))
            except Exception:
                continue
            if not labels[i] and row.get("period"):
                labels[i] = str(row.get("period"))

    forecast = []
    for i in range(periods):
        vals = horizons[i]
        if not vals:
            continue
        forecast.append({
            "period": labels[i] or f"t+{i+1}",
            "yhat": round(statistics.median(vals), 2),
            "yhat_lower": round(min(vals), 2),
            "yhat_upper": round(max(vals), 2),
            "n_samples": len(vals),
        })
    if not forecast:
        return {"success": False, "reason": "no_forecast",
                "message": "Empty forecast.", "disclaimer": LP.AI_ESTIMATE}

    first = horizons[0]
    conf = "low"
    if len(first) >= 2 and statistics.median(first):
        spread = (max(first) - min(first)) / abs(statistics.median(first))
        conf = "high" if spread <= 0.10 else ("med" if spread <= 0.30 else "low")
    assumptions = next((str(p.get("assumptions")) for p in parsed if p.get("assumptions")), "")
    direction = next((str(p.get("direction")) for p in parsed if p.get("direction")), "")

    return {
        "success": True,
        "measure": measure,
        "periods": periods,
        "history": history[-12:],
        "forecast": forecast,
        "assumptions": assumptions,
        "direction": direction,
        "confidence": conf,
        "model": str(getattr(rmodel, "model_id", None) or getattr(rmodel, "name", "")),
        "method": "llm_reasoning",
        "disclaimer": LP.AI_ESTIMATE,
    }
