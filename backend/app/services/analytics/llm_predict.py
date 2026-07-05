"""LLM-as-predictor primitives (BI-uplift Phase 7, flag HYBRID_ADV_METHODS).

The user's constraint: NO local/hosted ML model (no statsmodels/sklearn/mlxtend/
scipy, no Chronos/TimeGPT). Prediction is done by REASONING over real numbers,
following two proven zero-shot paradigms:

  * LLMTime  (Gruver et al.) — serialize a numeric series as text, let the LLM
    extrapolate; sample N times for a prediction interval (self-consistency).
  * TabLLM   (Hegselmann et al.) — serialize a table row to a sentence, let the
    LLM classify/score in-context.

Honesty: pandas only COUNTS/serializes real values (never invents them); the LLM
reasons. Every output is stamped AI_ESTIMATE. Route to a reasoning model
(prefers Claude Opus via auto_model's reason tier) because System-2 reasoning
beats System-1 for zero-shot forecasting.

All helpers are fail-soft.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

AI_ESTIMATE = "AI estimate — LLM reasoning over your real data, not a trained statistical model."


# --- model routing ----------------------------------------------------------

async def resolve_reason_model(db, organization, fallback=None):
    """Return an org LLMModel biased to the reasoning tier (prefers Claude Opus).
    Falls back to `fallback` (usually runtime_ctx['model']) then org default.
    Never raises."""
    try:
        from sqlalchemy import select
        from app.models.llm_model import LLMModel
        from app.ai.knowledge.auto_model import pick_model_for_tier
        rows = list((await db.execute(
            select(LLMModel).where(
                LLMModel.organization_id == organization.id,
                LLMModel.is_enabled == True,  # noqa: E712
            )
        )).scalars().all())
        default = fallback
        if default is None:
            try:
                from app.services.llm_service import LLMService
                default = await LLMService().get_default_model(db, organization)
            except Exception:
                default = rows[0] if rows else None
        if not rows:
            return default
        return pick_model_for_tier("reason", rows, default_model=default)
    except Exception as e:  # noqa: BLE001
        logger.debug("resolve_reason_model failed: %s", e)
        return fallback


def _infer_call(model, prompt: str, scope: str = "llm_predict") -> str:
    from app.ai.llm.llm import LLM
    from app.dependencies import async_session_maker
    return LLM(model, usage_session_maker=async_session_maker).inference(
        prompt, usage_scope=scope, should_record=True)


async def infer(model, prompt: str, scope: str = "llm_predict") -> str:
    """One reasoning-model call, off-thread (LLM.inference is sync). '' on error."""
    if model is None:
        return ""
    try:
        return (await asyncio.to_thread(_infer_call, model, prompt, scope) or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.debug("infer failed: %s", e)
        return ""


async def infer_samples(model, prompt: str, n: int = 3, scope: str = "llm_predict") -> list[str]:
    """N independent calls for self-consistency (uncertainty). Sequential to
    respect provider rate limits; each fail-soft."""
    out = []
    for _ in range(max(1, n)):
        r = await infer(model, prompt, scope)
        if r:
            out.append(r)
    return out


# --- json parsing -----------------------------------------------------------

def extract_json(text_in: str) -> Optional[dict]:
    if not text_in:
        return None
    for c in (text_in, re.sub(r"^```(?:json)?|```$", "", text_in.strip(), flags=re.M)):
        try:
            return json.loads(c)
        except Exception:
            pass
    m = re.search(r"\{.*\}", text_in, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


# --- data fetch (current in-conversation result) ----------------------------

async def fetch_latest_step_df(runtime_ctx, limit: int = 1):
    """The report's most recent successful create_data result as a DataFrame
    (LLMTime/TabLLM operate on this). Returns (df, None) or (None, reason).
    Reaches steps via LoadablesResolver — NOT the dead `last_result_df` key."""
    try:
        from app.ai.code_execution.loadables import LoadablesResolver, grid_to_df
        from app.services.parquet_store import hydrate as _hydrate
        resolver = LoadablesResolver(
            db=runtime_ctx.get("db"),
            organization=runtime_ctx.get("organization"),
            report=runtime_ctx.get("report"),
            current_user=runtime_ctx.get("user"),
        )
        steps = await resolver._report_default_steps(limit=limit)
        if not steps:
            return None, "no result yet — run a query first, then predict"
        step = steps[0]
        df = grid_to_df(_hydrate(step.data) if isinstance(step.data, dict) else {})
        if df is None or len(df) == 0:
            return None, "the latest result is empty"
        return df, None
    except Exception as e:  # noqa: BLE001
        logger.debug("fetch_latest_step_df failed: %s", e)
        return None, f"could not read the latest result: {e}"


# --- serialization (LLMTime / TabLLM encodings) -----------------------------

def guess_series(df) -> Optional[tuple]:
    """Best-effort (date_col, value_col) for a time series. None if not found."""
    try:
        import pandas as pd
        date_col = None
        for c in df.columns:
            n = str(c).lower()
            if any(h in n for h in ("date", "month", "period", "day", "week", "quarter", "year", "time")):
                date_col = c
                break
        if date_col is None:
            for c in df.columns:
                if pd.to_datetime(df[c].astype(str).head(10), errors="coerce").notna().mean() >= 0.7:
                    date_col = c
                    break
        num_cols = [c for c in df.columns if c != date_col and pd.to_numeric(df[c], errors="coerce").notna().mean() >= 0.7]
        if date_col is None or not num_cols:
            return None
        value_col = max(num_cols, key=lambda c: float(pd.to_numeric(df[c], errors="coerce").abs().sum() or 0))
        return date_col, value_col
    except Exception:
        return None


def serialize_series(df, date_col, value_col, cap: int = 60) -> list[dict]:
    """Clean (period, value) points, oldest→newest, for the LLMTime prompt."""
    try:
        import pandas as pd
        d = df[[date_col, value_col]].copy()
        d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
        d[value_col] = pd.to_numeric(d[value_col], errors="coerce")
        d = d.dropna().sort_values(date_col).tail(cap)
        return [{"period": str(p.date()) if hasattr(p, "date") else str(p),
                 "value": round(float(v), 4)}
                for p, v in zip(d[date_col], d[value_col])]
    except Exception:
        return []
