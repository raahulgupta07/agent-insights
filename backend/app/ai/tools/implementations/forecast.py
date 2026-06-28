"""forecast_df Tool — statistical time-series forecast on the last query result.

Wave1 P3. Given a date column + value column from the agent's last
create_data result, fits a Holt-Winters/ETS model (statsmodels, with a
numpy-linear fallback) and returns a forecast df (yhat, yhat_lower,
yhat_upper, ds) for N future periods, plus an optional LLM narrative.
No Prophet / pystan — light dep, deterministic numbers.

Self-gates on ``flags.FORECAST``: when OFF the tool is hidden from the
planner catalog (registry.py ``get_catalog_for_plan_type`` excludes it by
name) and if somehow called returns a benign disabled message — so a fresh
deploy behaves exactly like upstream. The numeric stack is imported LAZILY
inside ``run_stream`` so a missing installation never breaks boot.

Native ToolRegistry pattern (auto-registered by dropping this file in
implementations/). Mirrors ``resolve_metric.py`` structure.
"""
from typing import AsyncIterator, Dict, Any, Type
import logging

from pydantic import BaseModel

from app.ai.tools.base import Tool
from app.ai.tools.metadata import ToolMetadata
from app.ai.tools.schemas.events import (
    ToolEvent,
    ToolStartEvent,
    ToolEndEvent,
    ToolErrorEvent,
)
from app.ai.tools.schemas.forecast import (
    ForecastInput,
    ForecastOutput,
    ForecastRow,
)
from app.settings.hybrid_flags import flags

logger = logging.getLogger(__name__)


class ForecastDfTool(Tool):
    """Fit Prophet on a date+value series and return future forecast rows."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="forecast_df",
            description=(
                "Forecast future values from a date+value time series (Holt-Winters/ETS). "
                "Pass the date column name and the numeric value column name from "
                "the last create_data result, plus how many periods ahead to forecast. "
                "Returns ds (date), yhat (forecast), yhat_lower, yhat_upper columns plus a "
                "plain-English narrative. Use when the user asks for a forecast, prediction, or projection."
            ),
            category="both",
            version="1.0.0",
            input_schema=ForecastInput.model_json_schema(),
            output_schema=ForecastOutput.model_json_schema(),
            max_retries=1,
            timeout_seconds=120,
            idempotent=True,
            tags=["forecast", "timeseries", "analytics"],
            examples=[
                {
                    "input": {
                        "date_column": "order_date",
                        "value_column": "revenue",
                        "periods": 30,
                        "freq": "D",
                    },
                    "description": "30-day daily revenue forecast from last query result",
                },
                {
                    "input": {
                        "date_column": "month",
                        "value_column": "sales",
                        "periods": 6,
                        "freq": "M",
                    },
                    "description": "6-month sales forecast",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return ForecastInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return ForecastOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        # --- Input validation ------------------------------------------------
        try:
            data = ForecastInput(**tool_input)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"},
            )
            return

        yield ToolStartEvent(
            type="tool.start",
            payload={
                "date_column": data.date_column,
                "value_column": data.value_column,
                "periods": data.periods,
                "freq": data.freq,
            },
        )

        # --- Flag gate -------------------------------------------------------
        if not flags.FORECAST:
            output = ForecastOutput(
                success=True,
                message="Forecasting tool is not enabled (HYBRID_FORECAST=0).",
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": "Forecasting disabled; no forecast produced."},
                },
            )
            return

        # --- Lazy-import numeric stack (never break boot if absent) ----------
        # Engine = statsmodels Holt-Winters/ETS (light dep, deterministic), with a
        # pure-numpy linear fallback. No Prophet / pystan / 200MB image bloat.
        try:
            import numpy as np  # already in image
            import pandas as pd  # already in image
        except ImportError as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": f"numpy/pandas is not available: {e}",
                    "code": "MISSING_DEPENDENCY",
                },
            )
            return

        # --- Get the last result df from runtime context ---------------------
        # The agent's sandbox stores the last create_data result as a DataFrame
        # under the key 'last_result_df'. If absent, we cannot proceed.
        last_df = runtime_ctx.get("last_result_df")
        if last_df is None:
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": (
                        "No result dataframe found in context. "
                        "Run create_data first to produce a date+value table, "
                        "then call forecast_df."
                    ),
                    "code": "NO_DATA",
                },
            )
            return

        # --- Validate columns ------------------------------------------------
        try:
            df = pd.DataFrame(last_df)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Could not read result as DataFrame: {e}", "code": "DATA_ERROR"},
            )
            return

        if data.date_column not in df.columns:
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": (
                        f"Column '{data.date_column}' not found in result. "
                        f"Available columns: {list(df.columns)}"
                    ),
                    "code": "COLUMN_NOT_FOUND",
                },
            )
            return

        if data.value_column not in df.columns:
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": (
                        f"Column '{data.value_column}' not found in result. "
                        f"Available columns: {list(df.columns)}"
                    ),
                    "code": "COLUMN_NOT_FOUND",
                },
            )
            return

        # --- Build clean (ds, y) series --------------------------------------
        try:
            ts = df[[data.date_column, data.value_column]].copy()
            ts.columns = ["ds", "y"]
            ts["ds"] = pd.to_datetime(ts["ds"], errors="coerce")
            ts["y"] = pd.to_numeric(ts["y"], errors="coerce")
            ts = ts.dropna(subset=["ds", "y"]).sort_values("ds").reset_index(drop=True)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Could not build series: {e}", "code": "DATA_ERROR"},
            )
            return

        if len(ts) < 2:
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": (
                        f"Need at least 2 valid date+value rows to forecast, got {len(ts)}."
                    ),
                    "code": "INSUFFICIENT_DATA",
                },
            )
            return

        # --- Forecast: statsmodels ETS, numpy-linear fallback ----------------
        try:
            y = ts["y"].astype(float).to_numpy()
            n = len(y)
            freq = (data.freq or "D").upper()
            # Seasonal cycle length per frequency (0 = no seasonality available).
            seasonal_periods = {"H": 24, "D": 7, "W": 52, "M": 12, "Q": 4}.get(freq, 0)
            method = "linear"
            yhat = None
            resid_std = 0.0

            # Try ETS (additive trend; add seasonality only with ≥2 full cycles).
            try:
                from statsmodels.tsa.holtwinters import ExponentialSmoothing

                if seasonal_periods and n >= 2 * seasonal_periods:
                    es = ExponentialSmoothing(
                        y, trend="add", seasonal="add",
                        seasonal_periods=seasonal_periods,
                        initialization_method="estimated",
                    )
                    method = "ets"
                elif n >= 3:
                    es = ExponentialSmoothing(
                        y, trend="add", seasonal=None,
                        initialization_method="estimated",
                    )
                    method = "ets_trend"
                else:
                    raise ValueError("too few points for ETS")

                fit = es.fit()
                yhat = np.asarray(fit.forecast(data.periods), dtype=float)
                resid = y - np.asarray(fit.fittedvalues, dtype=float)
                resid_std = float(np.nanstd(resid)) if resid.size else 0.0
            except Exception as ets_err:
                # Linear (least-squares) fallback — always works for n ≥ 2.
                logger.info("forecast ETS unavailable, linear fallback: %s", ets_err)
                method = "linear"
                x = np.arange(n, dtype=float)
                coef = np.polyfit(x, y, 1)
                fx = np.arange(n, n + data.periods, dtype=float)
                yhat = coef[0] * fx + coef[1]
                resid = y - (coef[0] * x + coef[1])
                resid_std = float(np.nanstd(resid)) if resid.size else 0.0

            # Prediction band: ±1.96σ widening slowly with horizon (cap 3×).
            steps = np.arange(1, data.periods + 1, dtype=float)
            band = 1.96 * resid_std * np.minimum(np.sqrt(steps), 3.0)

            # Future dates: continue from last observed at the requested freq.
            last_obs_date = ts["ds"].max()
            future_dates = pd.date_range(
                start=last_obs_date, periods=data.periods + 1, freq=freq
            )[1:]

            rows = [
                ForecastRow(
                    ds=future_dates[i].isoformat(),
                    yhat=float(yhat[i]),
                    yhat_lower=float(yhat[i] - band[i]),
                    yhat_upper=float(yhat[i] + band[i]),
                )
                for i in range(len(yhat))
            ]
        except Exception as e:
            logger.exception(f"forecast_df failed: {e}")
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Forecast failed: {e}", "code": "FORECAST_FAILED"},
            )
            return

        # --- Optional LLM narrative (fail-soft; numbers stand alone) ----------
        narrative = None
        try:
            model_obj = runtime_ctx.get("model")
            if model_obj is not None and rows:
                last_actual = float(y[-1])
                first_fc = rows[0].yhat
                last_fc = rows[-1].yhat
                pct = ((last_fc - last_actual) / last_actual * 100.0) if last_actual else 0.0
                prompt = (
                    "You are a data analyst. In 2 short sentences, plainly describe this "
                    f"forecast for '{data.value_column}'. No preamble, no markdown.\n"
                    f"- Method: {method}\n"
                    f"- Last actual: {last_actual:,.2f}\n"
                    f"- Forecast horizon: {len(rows)} periods ({freq})\n"
                    f"- First forecast: {first_fc:,.2f}; last forecast: {last_fc:,.2f}\n"
                    f"- Net change over horizon: {pct:+.1f}%\n"
                    "Mention direction (up/down/flat) and rough magnitude. Be concrete."
                )
                import asyncio
                from app.ai.llm.llm import LLM
                from app.dependencies import async_session_maker

                def _call() -> str:
                    return LLM(model_obj, usage_session_maker=async_session_maker).inference(
                        prompt, usage_scope="forecast", should_record=True
                    )

                narrative = (await asyncio.to_thread(_call) or "").strip() or None
        except Exception as e:
            logger.info("forecast narrative skipped: %s", e)
            narrative = None

        msg = (
            f"Forecast produced: {len(rows)} periods ({freq}) for "
            f"'{data.value_column}' via {method}."
        )
        output = ForecastOutput(
            success=True,
            rows=rows,
            periods=len(rows),
            date_column=data.date_column,
            value_column=data.value_column,
            method=method,
            narrative=narrative,
            message=msg,
        )
        yield ToolEndEvent(
            type="tool.end",
            payload={
                "output": output.model_dump(),
                "observation": {
                    "summary": (msg + (f" {narrative}" if narrative else "")),
                    "artifacts": [
                        {
                            "type": "forecast",
                            "date_column": data.date_column,
                            "value_column": data.value_column,
                            "method": method,
                            "periods": len(rows),
                            "narrative": narrative,
                            "rows": [r.model_dump() for r in rows[:5]],  # preview
                        }
                    ],
                },
            },
        )
