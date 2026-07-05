"""classify_llm — zero-shot per-row classification / scoring by LLM (TabLLM pattern).

No trained model: each real row is serialized to text and a reasoning model
assigns a label + confidence + reason, using the column NAMES and values as
context. Good for churn risk, lead/deal scoring, at-risk flags, tiering.
Gated by HYBRID_ADV_METHODS. Operates on the latest in-conversation result.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, Field

from app.ai.tools.base import Tool
from app.ai.tools.metadata import ToolMetadata
from app.ai.tools.schemas.events import (
    ToolEvent, ToolStartEvent, ToolProgressEvent, ToolEndEvent, ToolErrorEvent,
)

logger = logging.getLogger(__name__)

_MAX_ROWS = 40  # keep the prompt bounded; classification stays per-row honest


class ClassifyLLMInput(BaseModel):
    target: str = Field(..., description="What to predict, e.g. 'churn risk', 'lead quality', 'at-risk'.")
    labels: Optional[List[str]] = Field(None, description="Allowed labels (default: High/Medium/Low).")
    key_column: Optional[str] = Field(None, description="Column that identifies each row (auto-detected if omitted).")


class ClassifyLLMTool(Tool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="classify_llm",
            description=(
                "Predict a per-row label or risk score by LLM reasoning (no trained "
                "model). Use after a query returns one row per entity (customers, "
                "leads, accounts) and the user asks who will churn / which leads are "
                "hot / which are at risk. Returns a label + confidence + reason per "
                "row, labelled an AI estimate."
            ),
            category="both",
            input_schema=ClassifyLLMInput.model_json_schema(),
            max_retries=1,
            timeout_seconds=120,
            idempotent=True,
            tags=["classification", "churn", "scoring", "prediction", "ai-estimate"],
        )

    @property
    def input_model(self):
        return ClassifyLLMInput

    async def run_stream(self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]) -> AsyncIterator[ToolEvent]:
        try:
            data = ClassifyLLMInput(**(tool_input or {}))
        except Exception as e:  # noqa: BLE001
            yield ToolErrorEvent(type="tool.error", payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"})
            return

        yield ToolStartEvent(type="tool.start", payload={"target": data.target})

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

        cols = list(df.columns)
        # key column: explicit, else a name that looks like an id/name, else index
        key_col = data.key_column if (data.key_column in cols) else None
        if key_col is None:
            for c in cols:
                n = str(c).lower()
                if n.endswith("id") or n in ("id", "name", "customer", "account", "email"):
                    key_col = c
                    break

        labels = data.labels or ["High", "Medium", "Low"]
        rows = df.head(_MAX_ROWS).to_dict(orient="records")
        truncated = len(df) > _MAX_ROWS

        # TabLLM serialization: one sentence per row from column=value pairs
        def serialize_row(r: dict) -> str:
            parts = []
            for c in cols:
                v = r.get(c)
                if v is None or str(v) == "" or str(v).lower() == "nan":
                    continue
                parts.append(f"{c}={v}")
            return "; ".join(parts)[:600]

        serialized = [{"key": str(r.get(key_col)) if key_col else str(i),
                       "text": serialize_row(r)} for i, r in enumerate(rows)]

        yield ToolProgressEvent(type="tool.progress", payload={"stage": "reasoning", "rows": len(serialized)})

        model = await LP.resolve_reason_model(
            runtime_ctx.get("db"), runtime_ctx.get("organization"), fallback=runtime_ctx.get("model"))

        rows_txt = "\n".join(f'[{s["key"]}] {s["text"]}' for s in serialized)
        prompt = (
            f"You are a predictive analyst. Classify each row below for: {data.target}. "
            f"Allowed labels: {labels}. Use ONLY the fields given; reason about what they "
            "imply. If a row lacks signal, use the safest label and low confidence. Think, "
            "then answer.\n\n"
            f"ROWS (each prefixed with its key in brackets):\n{rows_txt}\n\n"
            "Return STRICT JSON only, no prose, no code fences:\n"
            '{"predictions":[{"key":"<key>","label":"<one of the allowed labels>",'
            '"confidence":"high|med|low","reason":"<short, cite a field>"}]}'
        )

        raw = await LP.infer(model, prompt, scope="classify_llm")
        parsed = LP.extract_json(raw)
        preds_in = (parsed or {}).get("predictions") if isinstance(parsed, dict) else None
        if not isinstance(preds_in, list) or not preds_in:
            yield ToolErrorEvent(type="tool.error", payload={
                "error": "The model did not return usable predictions.", "code": "NO_PREDICTIONS"})
            return

        label_set = {str(x).lower() for x in labels}
        preds = []
        counts: Dict[str, int] = {}
        for p in preds_in:
            if not isinstance(p, dict):
                continue
            label = str(p.get("label", "")).strip()
            if label.lower() not in label_set:
                # snap to closest allowed label by prefix, else skip
                match = next((l for l in labels if l.lower().startswith(label.lower()[:3])), None)
                if not match:
                    continue
                label = match
            conf = str(p.get("confidence", "")).strip().lower()
            conf = conf if conf in ("high", "med", "low") else "low"
            preds.append({
                "key": str(p.get("key", "")).strip()[:120],
                "label": label,
                "confidence": conf,
                "reason": str(p.get("reason", "")).strip()[:240],
            })
            counts[label] = counts.get(label, 0) + 1

        if not preds:
            yield ToolErrorEvent(type="tool.error", payload={"error": "no valid predictions", "code": "NO_PREDICTIONS"})
            return

        dist = ", ".join(f"{v} {k}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        summary = (f"AI-estimated {data.target} for {len(preds)} rows: {dist}."
                   + (f" (first {_MAX_ROWS} rows)" if truncated else ""))

        yield ToolEndEvent(type="tool.end", payload={
            "output": {
                "success": True,
                "target": data.target,
                "labels": labels,
                "predictions": preds,
                "distribution": counts,
                "rows_scored": len(preds),
                "truncated": truncated,
                "method": "llm_reasoning",
                "disclaimer": LP.AI_ESTIMATE,
            },
            "observation": {"summary": summary},
        })


TOOL = ClassifyLLMTool
