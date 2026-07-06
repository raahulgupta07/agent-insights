"""Auto model selection (HYBRID_AUTO_MODEL).

Given a user question and the org's enabled models, pick the cheapest model that
can handle the question's complexity. Three tiers — FAST / BALANCED / REASON —
mapped onto whatever models the org actually has (ranked by output cost).

Design mirrors ``sense_maker.py``: cheap, fail-soft, NEVER raises. A deterministic
heuristic scores the question first ($0, ~0ms); only a fuzzy mid-band question
triggers ONE cheap LLM tie-break call (reusing the org's small model). If anything
goes wrong the caller falls back to the org default model — behaviour is identical
to the feature being OFF.

Returns ``(model, decision)`` where ``decision`` is a small dict suitable for
logging and for a FE "Auto → <Model>" badge:
    {"tier": "reason", "score": 0.74, "reason": "...", "model": "Claude 4.6 Opus",
     "via": "heuristic"|"llm"|"fallback"}
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heuristic scoring
# ---------------------------------------------------------------------------

# Small / cheap models — used to classify a model into the FAST tier.
_SMALL_MODEL_RE = re.compile(
    r"mini|haiku|flash|lite|small|nano|router|gpt-3|gpt-4o-mini|8b|7b|3b", re.I
)
# Flagship / heavy-reasoning models — the REASON tier prefers these.
_REASON_MODEL_RE = re.compile(r"opus|gpt-5\.5|ultra|-pro\b|gemini-3-pro", re.I)

# Words that signal genuine analytical depth (push toward REASON).
_HARD_RE = re.compile(
    r"\b(forecast|predict|project(?:ion)?|why|because|root cause|driver|drivers|"
    r"correlat\w*|regress\w*|trend|seasonal\w*|anomal\w*|compare|comparison|"
    r"versus|\bvs\b|breakdown|segment\w*|cohort|attribut\w*|explain|reason|"
    r"optimi[sz]e|scenario|what if|simulate|hypothes\w*|strateg\w*|"
    r"recommend\w*|diagnos\w*|investigat\w*)",
    re.I,
)
# Words that signal a trivial lookup (push toward FAST).
_EASY_RE = re.compile(
    r"\b(count|how many|list|show|display|what is|sum|total|average|avg|min|max|"
    r"top \d+|first|last|when|who|which|name)\b",
    re.I,
)
# Multi-step / chained intent.
_MULTISTEP_RE = re.compile(r"\b(then|after that|and also|followed by|step \d|first.*then)\b", re.I)
# Chart / artifact asks add a little weight (more tokens, more structure).
_ARTIFACT_RE = re.compile(r"\b(dashboard|chart|graph|plot|deck|slide|report|visuali[sz]e|pivot)\b", re.I)

# Tie-break band: scores inside this window are genuinely ambiguous → ask the LLM.
_FUZZY_LO = 0.40
_FUZZY_HI = 0.60


def score_complexity(question: str) -> Dict[str, Any]:
    """Deterministic 0..1 complexity score + the signals that produced it.

    Free, synchronous, never raises.
    """
    q = (question or "").strip()
    if not q:
        return {"score": 0.30, "tier": "fast", "signals": ["empty"]}

    signals: List[str] = []
    score = 0.30  # neutral baseline

    words = re.findall(r"\w+", q)
    n_words = len(words)
    # Length: long questions tend to carry more analytical intent.
    if n_words >= 45:
        score += 0.22; signals.append(f"long({n_words}w)")
    elif n_words >= 22:
        score += 0.12; signals.append(f"medium({n_words}w)")
    elif n_words <= 8:
        score -= 0.10; signals.append(f"short({n_words}w)")

    hard = len(_HARD_RE.findall(q))
    if hard:
        score += min(0.30, 0.12 * hard); signals.append(f"hard×{hard}")

    easy = len(_EASY_RE.findall(q))
    if easy and not hard:
        score -= min(0.18, 0.06 * easy); signals.append(f"easy×{easy}")

    if _MULTISTEP_RE.search(q):
        score += 0.15; signals.append("multistep")

    if _ARTIFACT_RE.search(q):
        score += 0.08; signals.append("artifact")

    # Question marks / conjunctions hint at compound asks.
    if q.count("?") >= 2 or q.lower().count(" and ") >= 2:
        score += 0.06; signals.append("compound")

    score = max(0.0, min(1.0, score))
    tier = "fast" if score < _FUZZY_LO else ("reason" if score > _FUZZY_HI else "balanced")
    return {"score": round(score, 3), "tier": tier, "signals": signals, "n_words": n_words}


# ---------------------------------------------------------------------------
# Tier -> concrete model
# ---------------------------------------------------------------------------

def _model_cost(m: Any) -> float:
    """Output cost per Mtok (the dominant cost driver). Unknown → mid (5.0)."""
    try:
        r = m.get_output_cost_rate()
        if r is not None:
            return float(r)
    except Exception:
        pass
    return 5.0


def _is_small(m: Any) -> bool:
    mid = str(getattr(m, "model_id", "") or "")
    nm = str(getattr(m, "name", "") or "")
    return bool(_SMALL_MODEL_RE.search(mid) or _SMALL_MODEL_RE.search(nm))


def _is_reason(m: Any) -> bool:
    mid = str(getattr(m, "model_id", "") or "")
    nm = str(getattr(m, "name", "") or "")
    return bool(_REASON_MODEL_RE.search(mid) or _REASON_MODEL_RE.search(nm))


def pick_model_for_tier(tier: str, models: List[Any], *, default_model: Any) -> Any:
    """Map a tier onto a concrete enabled model. Always returns something usable.

    FAST   → cheapest small model (fallback cheapest overall).
    REASON → flagship model (regex) else most expensive (proxy for most capable).
    BALANCED → median-cost model, preferring a non-small one.
    """
    usable = [m for m in (models or []) if getattr(m, "model_id", None)]
    if not usable:
        return default_model
    by_cost = sorted(usable, key=_model_cost)

    if tier == "fast":
        smalls = [m for m in by_cost if _is_small(m)]
        return (smalls[0] if smalls else by_cost[0])

    if tier == "reason":
        reasons = [m for m in usable if _is_reason(m)]
        if reasons:
            return sorted(reasons, key=_model_cost, reverse=True)[0]
        return by_cost[-1]

    # balanced — prefer a non-small mid model.
    non_small = [m for m in by_cost if not _is_small(m)]
    pool = non_small or by_cost
    return pool[len(pool) // 2]


# ---------------------------------------------------------------------------
# Fast codegen tier (HYBRID_FAST_CODEGEN) — pure code-generation downshift
# ---------------------------------------------------------------------------

def codegen_model(*, default_model: Any, small_model: Any = None, models: Optional[List[Any]] = None) -> Any:
    """Model to use for a PURE code-generation step (create_data's Coder).

    Code generation (write SQL/pandas from a known schema) does not need the
    reasoning model — the org's fast/small model (its ``is_small_default`` row,
    currently a Gemini flash-lite) runs it 3-5x cheaper/faster. Reasoning,
    planning and reflection stay on ``default_model`` at the call site; only this
    one step is downshifted.

    Prefers the caller-supplied ``small_model`` (the resolved is_small_default);
    else reuses the existing FAST-tier picker over ``models`` (cheapest small
    model). NEVER raises → falls back to ``default_model`` (feature OFF behaviour).
    Reuses the FAST model already known to the org — no hardcoded model string.
    """
    try:
        if small_model is not None and getattr(small_model, "model_id", None):
            return small_model
        chosen = pick_model_for_tier("fast", models or [], default_model=default_model)
        return chosen or default_model
    except Exception:
        logger.warning("auto_model: codegen_model failed", exc_info=True)
        return default_model


# ---------------------------------------------------------------------------
# Optional cheap LLM tie-break (only for the fuzzy mid-band)
# ---------------------------------------------------------------------------

_TIE_PROMPT = (
    "You are a routing classifier for a data-analytics assistant. Decide how much "
    "reasoning a question needs. Reply with ONE word only: FAST, BALANCED, or REASON.\n"
    "FAST = a simple lookup/count/list. BALANCED = normal analysis or a single chart. "
    "REASON = forecasting, multi-step, why/root-cause, correlation, comparison across "
    "segments, or strategy.\n\nQUESTION:\n{q}\n\nANSWER (one word):"
)


async def _llm_tiebreak(small_model: Any, question: str) -> Optional[str]:
    try:
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        prompt = _TIE_PROMPT.format(q=(question or "").strip()[:600])

        def _infer() -> str:
            return LLM(small_model, usage_session_maker=async_session_maker).inference(
                prompt, usage_scope="auto_model"
            )

        raw = await asyncio.to_thread(_infer)
        if not raw:
            return None
        t = raw.strip().upper()
        for tier in ("REASON", "BALANCED", "FAST"):
            if tier in t:
                return tier.lower()
        return None
    except Exception:
        logger.warning("auto_model: llm tiebreak failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_TIER_ORDER = {"fast": 0, "balanced": 1, "reason": 2}


def _floor_tier(tier: str, min_tier: Optional[str]) -> str:
    """Raise ``tier`` to at least ``min_tier`` (never lowers it)."""
    if not min_tier:
        return tier
    if _TIER_ORDER.get(min_tier, 0) > _TIER_ORDER.get(tier, 0):
        return min_tier
    return tier


# Connectors whose query IS generated code against a live semantic model (DAX) —
# a weak FAST-tier model invents generic table/measure names and fails.
_DAX_CONNECTOR_KINDS = {"powerbi", "powerbi_user", "ms_fabric", "ms_fabric_user"}


def capability_floor(
    *,
    connector_kinds: Optional[List[str]] = None,
    table_count: int = 0,
    question: str = "",
) -> str:
    """Minimum tier a query REQUIRES based on WHAT it touches (not just keywords).

    A cheap FAST-tier model is unsafe for code-gen connectors and multi-table joins,
    so this raises a floor by structure:
      · Power BI / Fabric (DAX) present   → at least BALANCED (never route DAX to FAST).
      · a join (>= 2 active tables)        → at least BALANCED.
      · genuine analytical depth in the    → REASON
        question (forecast / why / root-cause / correlation / dashboard / deck …,
        via the shared ``_HARD_RE`` / ``_ARTIFACT_RE``).
      · otherwise                          → FAST.

    Pure + synchronous. NEVER raises → returns ``"fast"`` on any error.
    """
    try:
        floor = "fast"
        kinds = {str(k).lower() for k in (connector_kinds or []) if k}
        if kinds & _DAX_CONNECTOR_KINDS:
            floor = "balanced"
        if (table_count or 0) >= 2 and _TIER_ORDER[floor] < _TIER_ORDER["balanced"]:
            floor = "balanced"
        q = question or ""
        if _HARD_RE.search(q) or _ARTIFACT_RE.search(q):
            floor = "reason"
        return floor
    except Exception:
        return "fast"


async def choose_auto_model(
    *,
    question: str,
    models: List[Any],
    default_model: Any,
    small_model: Any = None,
    allow_llm: bool = True,
    min_tier: Optional[str] = None,
    connector_kinds: Optional[List[str]] = None,
    table_count: int = 0,
) -> Tuple[Any, Dict[str, Any]]:
    """Pick the best model for ``question`` from ``models``. NEVER raises.

    Returns ``(model, decision)``. On any failure returns the default model with a
    ``via='fallback'`` decision so the caller behaves exactly as if AUTO were OFF.

    ``min_tier`` (fast|balanced|reason) floors the chosen tier — used to keep
    code-generation connectors (Power BI / DAX, warehouses) off the weakest model
    even when the question text scores as trivial ("how many projects?").

    ``connector_kinds`` / ``table_count`` are OPTIONAL capability signals: when a
    caller passes them, a structural :func:`capability_floor` is computed and folded
    into ``min_tier`` (the STRONGER of the two wins). Callers that omit both new
    params are byte-identical to before (no capability floor is applied).
    """
    try:
        # Fold the structural capability floor into min_tier — only when the caller
        # opted in by passing capability signals (keeps existing callers unchanged).
        if connector_kinds is not None or table_count:
            cap = capability_floor(
                connector_kinds=connector_kinds,
                table_count=table_count,
                question=question,
            )
            if _TIER_ORDER.get(cap, 0) > _TIER_ORDER.get(min_tier or "", -1):
                min_tier = cap

        sc = score_complexity(question)
        tier = sc["tier"]
        via = "heuristic"
        reason = "+".join(sc.get("signals", [])) or "baseline"

        # Tie-break only in the genuinely ambiguous band, and only if we have a
        # cheap model to ask with (else stick with the heuristic).
        if allow_llm and small_model is not None and _FUZZY_LO <= sc["score"] <= _FUZZY_HI:
            llm_tier = await _llm_tiebreak(small_model, question)
            if llm_tier:
                tier = llm_tier
                via = "llm"
                reason = f"tiebreak→{llm_tier}"

        # Floor to the connector-required minimum tier (e.g. Power BI code-gen).
        floored = _floor_tier(tier, min_tier)
        if floored != tier:
            reason = f"{reason}|floor→{floored}({min_tier})"
            tier = floored

        chosen = pick_model_for_tier(tier, models, default_model=default_model)
        if chosen is None:
            chosen = default_model
        decision = {
            "tier": tier,
            "score": sc["score"],
            "reason": reason,
            "via": via,
            "model": getattr(chosen, "name", str(chosen)),
            "model_id": getattr(chosen, "model_id", None),
        }
        return chosen, decision
    except Exception:
        logger.warning("auto_model: choose_auto_model failed", exc_info=True)
        return default_model, {
            "tier": "balanced", "score": None, "reason": "error",
            "via": "fallback", "model": getattr(default_model, "name", None),
        }
