"""discover_llm — find associations / segments / relationships by LLM reasoning.

No mining engine (no apriori/kmeans): pandas COUNTS the real structure
(category shares, top co-occurring pairs, numeric correlations) and a reasoning
model turns those real numbers into plain-language findings — never inventing a
pattern that isn't in the counts. Gated by HYBRID_ADV_METHODS. Operates on the
latest in-conversation result.
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

_MODES = ("associations", "relationships", "segments")


class DiscoverLLMInput(BaseModel):
    mode: str = Field("associations",
                      description="associations (what goes together) | relationships (which numbers move together) | segments (natural groups).")
    focus: Optional[str] = Field(None, description="Optional question or column of interest to steer the discovery.")


class DiscoverLLMTool(Tool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="discover_llm",
            description=(
                "Discover hidden patterns in the latest result by LLM reasoning "
                "over REAL computed counts (no mining engine). mode=associations "
                "(which categories co-occur / market-basket style), relationships "
                "(which numeric fields move together), or segments (natural "
                "groupings). Returns grounded findings labelled an AI estimate."
            ),
            category="both",
            input_schema=DiscoverLLMInput.model_json_schema(),
            max_retries=1,
            timeout_seconds=120,
            idempotent=True,
            tags=["discovery", "association", "segmentation", "correlation", "ai-estimate"],
        )

    @property
    def input_model(self):
        return DiscoverLLMInput

    async def run_stream(self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]) -> AsyncIterator[ToolEvent]:
        try:
            data = DiscoverLLMInput(**(tool_input or {}))
        except Exception as e:  # noqa: BLE001
            yield ToolErrorEvent(type="tool.error", payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"})
            return

        mode = data.mode if data.mode in _MODES else "associations"
        yield ToolStartEvent(type="tool.start", payload={"mode": mode})

        from app.settings.hybrid_flags import flags
        if not flags.ADV_METHODS:
            yield ToolEndEvent(type="tool.end", payload={
                "output": {"success": False, "disabled": True},
                "observation": {"summary": "Advanced methods are turned off (HYBRID_ADV_METHODS)."},
            })
            return

        from app.services.analytics import llm_predict as LP
        from app.services.analytics import compute as C

        df, reason = await LP.fetch_latest_step_df(runtime_ctx)
        if df is None:
            yield ToolErrorEvent(type="tool.error", payload={"error": reason or "no data", "code": "NO_DATA"})
            return

        yield ToolProgressEvent(type="tool.progress", payload={"stage": "computing", "rows": len(df)})

        # --- COMPUTE the real structure (pandas only, never invented) ----------
        evidence: Dict[str, Any] = {"n_rows": int(len(df))}
        profile = C.profile_dataframe(df, table_name="latest_result")
        roles = {c["name"]: c["role"] for c in profile.get("columns", [])}
        cat_cols = [c for c, r in roles.items() if r == "categorical"]

        if mode == "relationships":
            evidence["correlations"] = C.correlation_pairs(df, threshold=0.3, top=12)
        else:
            # associations / segments both lean on category structure + co-occurrence
            if profile.get("category_shares"):
                evidence["category_shares"] = profile["category_shares"]
            if profile.get("ranking"):
                evidence["ranking"] = profile["ranking"]
            evidence["cooccurrence"] = _top_cooccurrence(df, cat_cols)
            if mode == "segments":
                evidence["correlations"] = C.correlation_pairs(df, threshold=0.3, top=6)

        has_signal = any(k for k in ("correlations", "category_shares", "cooccurrence", "ranking")
                         if evidence.get(k))
        if not has_signal:
            yield ToolEndEvent(type="tool.end", payload={
                "output": {"success": True, "mode": mode, "findings": [],
                           "disclaimer": LP.AI_ESTIMATE},
                "observation": {"summary": "No categorical/numeric structure to mine in the latest result."},
            })
            return

        yield ToolProgressEvent(type="tool.progress", payload={"stage": "reasoning"})

        model = await LP.resolve_reason_model(
            runtime_ctx.get("db"), runtime_ctx.get("organization"), fallback=runtime_ctx.get("model"))

        import json as _json
        spec = {
            "associations": "which values tend to appear together (market-basket style) and why it matters",
            "relationships": "which numeric fields move together and the likely business meaning",
            "segments": "natural groupings/segments implied by the shares and correlations",
        }[mode]
        prompt = (
            f"You are a data-mining analyst. Below are REAL computed statistics from "
            f"{evidence['n_rows']} rows. Identify {spec}. Use ONLY these numbers — do NOT "
            "invent a pattern that isn't supported by the evidence. Rank by strength.\n\n"
            + (f"Focus: {data.focus}\n\n" if data.focus else "")
            + f"EVIDENCE (JSON):\n{_json.dumps(evidence, default=str)[:4000]}\n\n"
            "Return STRICT JSON only, no prose, no code fences:\n"
            '{"findings":[{"pattern":"<what>","evidence":"<cite a real number/pair>",'
            '"strength":"strong|moderate|weak","action":"<what to do>"}]}'
        )

        raw = await LP.infer(model, prompt, scope="discover_llm")
        parsed = LP.extract_json(raw)
        found_in = (parsed or {}).get("findings") if isinstance(parsed, dict) else None
        findings: List[dict] = []
        if isinstance(found_in, list):
            for f in found_in:
                if not isinstance(f, dict) or not f.get("pattern"):
                    continue
                strength = str(f.get("strength", "")).strip().lower()
                strength = strength if strength in ("strong", "moderate", "weak") else "moderate"
                findings.append({
                    "pattern": str(f.get("pattern", "")).strip()[:240],
                    "evidence": str(f.get("evidence", "")).strip()[:240],
                    "strength": strength,
                    "action": str(f.get("action", "")).strip()[:240],
                })

        if not findings:
            yield ToolErrorEvent(type="tool.error", payload={
                "error": "The model did not return usable findings.", "code": "NO_FINDINGS"})
            return

        top = findings[0]["pattern"]
        summary = f"AI-discovered {len(findings)} {mode} pattern(s). Top: {top}"

        yield ToolEndEvent(type="tool.end", payload={
            "output": {
                "success": True,
                "mode": mode,
                "findings": findings,
                "evidence": evidence,
                "method": "llm_reasoning",
                "disclaimer": LP.AI_ESTIMATE,
            },
            "observation": {"summary": summary},
        })


def _top_cooccurrence(df, cat_cols: List[str], top: int = 10) -> List[dict]:
    """Real co-occurrence counts between the two most informative categorical
    columns (low-cardinality). Plain pandas crosstab — never invented."""
    try:
        import pandas as pd
        usable = [c for c in cat_cols if 2 <= df[c].nunique(dropna=True) <= 20]
        if len(usable) < 2:
            return []
        # pick the two with the most balanced cardinality
        usable = sorted(usable, key=lambda c: df[c].nunique(dropna=True))[:2]
        a, b = usable[0], usable[1]
        ct = pd.crosstab(df[a].astype(str), df[b].astype(str))
        pairs = []
        for ra in ct.index:
            for rb in ct.columns:
                n = int(ct.loc[ra, rb])
                if n > 0:
                    pairs.append((n, f"{a}={ra}", f"{b}={rb}"))
        pairs.sort(reverse=True)
        return [{"a": pa, "b": pb, "count": n} for n, pa, pb in pairs[:top]]
    except Exception:
        return []


TOOL = DiscoverLLMTool
