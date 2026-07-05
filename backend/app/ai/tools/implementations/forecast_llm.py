"""forecast_llm — zero-shot forecasting by LLM reasoning (LLMTime pattern).

No statistical/ML engine: the real series is serialized as text and a REASONING
model extrapolates it; sampled N times for a prediction interval + confidence.
Gated by HYBRID_ADV_METHODS. Operates on the latest in-conversation result.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, Field

from app.ai.tools.base import Tool
from app.ai.tools.metadata import ToolMetadata
from app.ai.tools.schemas.events import (
    ToolEvent, ToolStartEvent, ToolProgressEvent, ToolEndEvent, ToolErrorEvent,
)

logger = logging.getLogger(__name__)


class ForecastLLMInput(BaseModel):
    periods: int = Field(3, ge=1, le=24, description="How many future periods to predict.")
    date_column: Optional[str] = Field(None, description="Date/period column (auto-detected if omitted).")
    value_column: Optional[str] = Field(None, description="Numeric column to forecast (auto-detected if omitted).")


class ForecastLLMTool(Tool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="forecast_llm",
            description=(
                "Forecast a numeric time series into the future by LLM reasoning "
                "(no statistical model). Use after a query returns a date + value "
                "table (e.g. monthly revenue) and the user asks to predict / project "
                "the next periods. Returns a per-period estimate with a low–high range "
                "and assumptions, clearly labelled an AI estimate."
            ),
            category="both",
            input_schema=ForecastLLMInput.model_json_schema(),
            max_retries=1,
            timeout_seconds=120,
            idempotent=True,
            tags=["forecast", "prediction", "time-series", "ai-estimate"],
        )

    @property
    def input_model(self):
        return ForecastLLMInput

    async def run_stream(self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]) -> AsyncIterator[ToolEvent]:
        try:
            data = ForecastLLMInput(**(tool_input or {}))
        except Exception as e:  # noqa: BLE001
            yield ToolErrorEvent(type="tool.error", payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"})
            return

        yield ToolStartEvent(type="tool.start", payload={"periods": data.periods})

        from app.settings.hybrid_flags import flags
        if not flags.ADV_METHODS:
            yield ToolEndEvent(type="tool.end", payload={
                "output": {"success": False, "disabled": True},
                "observation": {"summary": "Advanced methods are turned off (HYBRID_ADV_METHODS)."},
            })
            return

        from app.services.analytics import llm_predict as LP

        df, reason = await LP.fetch_latest_step_df(runtime_ctx)
        if df is None:
            yield ToolErrorEvent(type="tool.error", payload={"error": reason or "no data", "code": "NO_DATA"})
            return

        # resolve series columns
        date_col, value_col = data.date_column, data.value_column
        if not (date_col and value_col):
            guessed = LP.guess_series(df)
            if not guessed:
                yield ToolErrorEvent(type="tool.error", payload={
                    "error": "Could not find a date + numeric column to forecast. "
                             f"Columns: {list(df.columns)}", "code": "NO_SERIES"})
                return
            date_col, value_col = date_col or guessed[0], value_col or guessed[1]

        points = LP.serialize_series(df, date_col, value_col)
        if len(points) < 3:
            yield ToolErrorEvent(type="tool.error", payload={
                "error": f"Need at least 3 clean points to forecast, got {len(points)}.",
                "code": "INSUFFICIENT_DATA"})
            return

        yield ToolProgressEvent(type="tool.progress", payload={"stage": "reasoning", "points": len(points)})

        model = await LP.resolve_reason_model(
            runtime_ctx.get("db"), runtime_ctx.get("organization"), fallback=runtime_ctx.get("model"))

        series_txt = "\n".join(f"{p['period']}: {p['value']}" for p in points)
        prompt = (
            "You are a forecasting analyst. Below is a real historical series "
            f"of '{value_col}' by '{date_col}'. Extrapolate the NEXT {data.periods} "
            "periods by reasoning about level, trend, and any repeating seasonality. "
            "Do NOT just repeat the last value; think step by step, then answer.\n\n"
            f"SERIES (oldest to newest):\n{series_txt}\n\n"
            "Return STRICT JSON only, no prose, no code fences:\n"
            '{"forecast":[{"period":"<label>","value":<number>}],'
            '"assumptions":"<one sentence>","direction":"up|down|flat",'
            '"confidence":"high|med|low"}'
        )

        samples = await LP.infer_samples(model, prompt, n=3, scope="forecast_llm")
        parsed: List[dict] = [p for p in (LP.extract_json(s) for s in samples) if isinstance(p, dict)]
        if not parsed:
            yield ToolErrorEvent(type="tool.error", payload={
                "error": "The model did not return a usable forecast.", "code": "NO_FORECAST"})
            return

        # self-consistency: align by index, per-period median + min/max band
        horizons: List[List[float]] = [[] for _ in range(data.periods)]
        labels: List[str] = ["" for _ in range(data.periods)]
        for pj in parsed:
            fc = pj.get("forecast") if isinstance(pj.get("forecast"), list) else []
            for i, row in enumerate(fc[:data.periods]):
                if not isinstance(row, dict):
                    continue
                try:
                    horizons[i].append(float(row.get("value")))
                except Exception:
                    continue
                if not labels[i] and row.get("period"):
                    labels[i] = str(row.get("period"))

        rows = []
        for i in range(data.periods):
            vals = horizons[i]
            if not vals:
                continue
            mid = statistics.median(vals)
            rows.append({
                "period": labels[i] or f"t+{i+1}",
                "yhat": round(mid, 4),
                "yhat_lower": round(min(vals), 4),
                "yhat_upper": round(max(vals), 4),
                "n_samples": len(vals),
            })
        if not rows:
            yield ToolErrorEvent(type="tool.error", payload={"error": "empty forecast", "code": "NO_FORECAST"})
            return

        # confidence from cross-sample spread of the first horizon
        first = horizons[0]
        conf = "low"
        if len(first) >= 2 and statistics.median(first):
            spread = (max(first) - min(first)) / abs(statistics.median(first))
            conf = "high" if spread <= 0.10 else ("med" if spread <= 0.30 else "low")
        assumptions = next((str(p.get("assumptions")) for p in parsed if p.get("assumptions")), "")
        direction = next((str(p.get("direction")) for p in parsed if p.get("direction")), "")

        last_actual = points[-1]["value"]
        pct = ((rows[-1]["yhat"] - last_actual) / last_actual * 100.0) if last_actual else 0.0
        summary = (f"AI-estimated forecast of {value_col}: {rows[-1]['yhat']:,.0f} in "
                   f"{rows[-1]['period']} ({pct:+.0f}% vs last actual {last_actual:,.0f}), "
                   f"{direction or 'trend'}, confidence {conf}.")

        yield ToolEndEvent(type="tool.end", payload={
            "output": {
                "success": True,
                "value_column": value_col,
                "date_column": date_col,
                "rows": rows,
                "assumptions": assumptions,
                "direction": direction,
                "confidence": conf,
                "method": "llm_reasoning",
                "disclaimer": LP.AI_ESTIMATE,
            },
            "observation": {"summary": summary},
        })


TOOL = ForecastLLMTool
