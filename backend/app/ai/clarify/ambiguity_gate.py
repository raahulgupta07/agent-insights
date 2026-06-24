"""
Ambiguity gate — "ask before assuming" (R3 / AmbiSQL pattern)
============================================================

Detects underspecified / ambiguous analytics questions BEFORE the planner runs
and, when a question is genuinely ambiguous, returns a single short clarifying
question plus up to 4 quick-pick options so the user can disambiguate instead of
the agent silently guessing.

This exists because of a real bug: the chinook demo's data was re-dated to
2021-2025, but the agent assumed ``year = 2009`` (chinook's classic dates from
its training prior) and returned 0 rows. The class of failure is AmbiRef-style
underspecification — a time window with no anchor, a year/period that may not
exist in the data, a metric with multiple plausible definitions, or a named
entity value that may not match what's stored. Rather than guess, we ask.

Design rules (CLAUDE.md HARD RULES 3/4/5 + LLM = OpenRouter ONLY):
- **Flag-gated, default OFF.** Self-gates on ``flags.AMBIGUITY_GATE`` (env
  ``HYBRID_AMBIGUITY_GATE``, added to ``hybrid_flags`` by the PARENT). Referenced
  defensively via ``getattr(flags, "AMBIGUITY_GATE", False)`` so importing/calling
  this module never crashes if the flag attribute does not exist yet. OFF ->
  ``ambiguous=False`` no-op, ZERO LLM calls.
- **NEVER raises.** The whole body is wrapped in try/except; on ANY error
  (flag missing, no model, LLM failure, JSON junk, ...) it degrades to the safe
  "not ambiguous" answer so the request path is never broken.
- **OpenRouter-only.** Uses the repo's existing ``LLM(model, ...).inference(...)``
  one-shot call shape — the exact same idiom the brain modules (distiller,
  knowledge_proposer) use. The cheap/small model is resolved via
  ``LLMService().get_default_model(db, organization, None, is_small=True)`` when a
  model isn't passed in. No new client, no new dependency (stdlib + repo LLM).
- **One cheap LLM call.** Classifies the question for AmbiRef-style ambiguity and
  is told to ONLY flag genuinely ambiguous/underspecified questions; a clear
  question returns ``ambiguous=False``.

This module is INERT on its own — it does not touch the agent. The PARENT wires
``detect_ambiguity`` into ``agent_v2`` BEFORE planning (and owns the flag
plumbing in ``hybrid_flags.py`` + compose/.env).

Public surface:
    async def detect_ambiguity(db, *, organization, question, schema_summary=None,
                               data_source_hint=None, model=None) -> dict
Returns:
    {"ambiguous": bool, "kind": str | None,
     "clarifying_question": str | None, "suggested_options": list[str]}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The ambiguity kinds we ask the model to classify into. Kept as a constant so a
# caller/parent can reference the vocabulary without re-deriving it.
KINDS = (
    "missing_date_range",
    "undefined_relative_time",
    "ambiguous_metric",
    "ambiguous_entity",
)

# Cap how many quick-pick options we return (contract: up to 4).
_MAX_OPTIONS = 4

# A safe, fully-formed "not ambiguous" answer. Every error path returns a copy.
_SAFE: dict = {
    "ambiguous": False,
    "kind": None,
    "clarifying_question": None,
    "suggested_options": [],
}


def _safe_result() -> dict:
    """Return a fresh copy of the safe (not-ambiguous) result."""
    return dict(_SAFE)


def build_ambiguity_prompt(
    question: str,
    schema_summary: Optional[str],
    data_source_hint: Optional[str],
) -> str:
    """Compose the one-shot ambiguity-classification prompt. Pure, deterministic.

    Asks the model to flag ONLY genuinely ambiguous/underspecified questions and
    to return, when ambiguous, a single short clarifying question + up to 4
    quick-pick options. Strict single-line JSON output.
    """
    schema_block = (
        f"Data source schema (table/column hints):\n{schema_summary}\n\n"
        if schema_summary
        else ""
    )
    hint_block = (
        f"Data source / domain hint:\n{data_source_hint}\n\n"
        if data_source_hint
        else ""
    )
    return (
        "You are an analytics ambiguity gate. Decide whether the user's question "
        "is too AMBIGUOUS or UNDERSPECIFIED to answer correctly without guessing. "
        "If you would have to ASSUME something the user did not state (and a wrong "
        "assumption would give a wrong answer), the question is ambiguous.\n\n"
        f"{hint_block}"
        f"{schema_block}"
        f"User question:\n{question}\n\n"
        "Flag the question ONLY for one of these ambiguity kinds:\n"
        "- missing_date_range: a time/trend question with NO year or period given, "
        "OR a specific year/period that may not exist in this data (e.g. asking "
        "'for 2009' when the data could be from different years). Datasets are "
        "often re-dated — never assume the year from a dataset's name or famous "
        "defaults; if the period is unstated or unverifiable, this is ambiguous.\n"
        "- undefined_relative_time: a relative window with no fixed anchor, e.g. "
        "'this year', 'current', 'recent', 'last quarter', 'YTD' — ambiguous unless "
        "the reference point is clear.\n"
        "- ambiguous_metric: a metric whose definition could differ, e.g. 'revenue', "
        "'sales', 'growth', 'active users', 'churn' — ambiguous when multiple "
        "reasonable definitions could apply.\n"
        "- ambiguous_entity: a named value (a product, region, customer, status, "
        "category, ...) that may not match a stored value, or could refer to more "
        "than one thing.\n\n"
        "IMPORTANT:\n"
        "- Flag ONLY genuinely ambiguous/underspecified questions. If the question "
        "is clear enough to answer without guessing, it is NOT ambiguous.\n"
        "- When ambiguous, write ONE short, friendly clarifying question and up to "
        "4 quick-pick options the user can choose from. For a year/period question, "
        "suggest plausible periods and include an 'All years' / 'All time' option. "
        "Keep each option short (a few words).\n\n"
        "Return ONLY a single-line JSON object, no prose, no markdown, with this "
        "exact shape:\n"
        '{"ambiguous": true|false, "kind": "missing_date_range"|'
        '"undefined_relative_time"|"ambiguous_metric"|"ambiguous_entity"|null, '
        '"clarifying_question": "<one short question or null>", '
        '"suggested_options": ["<opt1>", "<opt2>", ...]}\n\n'
        "If the question is clear, return "
        '{"ambiguous": false, "kind": null, "clarifying_question": null, '
        '"suggested_options": []}.\n'
        "Output the JSON object ONLY."
    )


def _parse_ambiguity(text: str) -> dict:
    """Best-effort parse + normalize the model's JSON into the contract shape.

    Tolerates code fences / surrounding prose by extracting the outermost JSON
    object. On any parse failure or off-shape payload -> the safe (not-ambiguous)
    result. Never raises.
    """
    if not text:
        return _safe_result()
    cleaned = text.strip()
    # Strip a leading ```json / ``` fence if present.
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    # Extract the outermost JSON object.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        parsed = json.loads(cleaned, strict=False)
    except Exception:
        return _safe_result()
    if not isinstance(parsed, dict):
        return _safe_result()

    # Normalize to the contract shape — only trust an explicit boolean True.
    ambiguous = parsed.get("ambiguous") is True
    if not ambiguous:
        return _safe_result()

    kind = parsed.get("kind")
    kind = kind if kind in KINDS else None

    cq = parsed.get("clarifying_question")
    clarifying_question = str(cq).strip() if cq else ""

    raw_opts = parsed.get("suggested_options")
    suggested_options: list[str] = []
    if isinstance(raw_opts, list):
        for opt in raw_opts:
            s = str(opt).strip() if opt is not None else ""
            if s:
                suggested_options.append(s)
            if len(suggested_options) >= _MAX_OPTIONS:
                break

    # A clarifying question is required for an ambiguous verdict to be useful;
    # without one we cannot actually ask, so degrade to not-ambiguous.
    if not clarifying_question:
        return _safe_result()

    return {
        "ambiguous": True,
        "kind": kind,
        "clarifying_question": clarifying_question,
        "suggested_options": suggested_options,
    }


async def detect_ambiguity(
    db: Any,
    *,
    organization: Any,
    question: str,
    schema_summary: Optional[str] = None,
    data_source_hint: Optional[str] = None,
    model: Any = None,
) -> dict:
    """Classify ``question`` for AmbiRef-style ambiguity via ONE cheap LLM call.

    Returns ``{"ambiguous", "kind", "clarifying_question", "suggested_options"}``.
    Flag-gated (default OFF -> not-ambiguous no-op, no LLM call) and NEVER raises —
    any error degrades to the safe not-ambiguous result.

    Args:
        db: async DB session (used only to resolve the cheap model when one
            isn't passed).
        organization: the org (used for model resolution + usage scoping).
        question: the user's natural-language question.
        schema_summary: optional compact schema text to ground the judgment.
        data_source_hint: optional data-source/domain hint string.
        model: an ``LLMModel`` to use; when None, the org's small/cheap default
            is resolved.
    """
    try:
        # 1. Flag gate. Defensive getattr so a missing flag attr -> OFF, no crash.
        from app.settings.hybrid_flags import flags

        if not getattr(flags, "AMBIGUITY_GATE", False):
            return _safe_result()

        # 2. Need a real question to classify.
        q = (question or "").strip()
        if not q:
            return _safe_result()

        # 3. Resolve the cheap/small model if the caller didn't pass one.
        #    (get_default_model only uses db + organization; user arg unused.)
        resolved_model = model
        if resolved_model is None:
            from app.services.llm_service import LLMService

            resolved_model = await LLMService().get_default_model(
                db, organization, None, is_small=True
            )
        if resolved_model is None:
            return _safe_result()

        # 4. ONE cheap one-shot LLM call — the exact OpenRouter idiom the brain
        #    modules use: LLM(model, usage_session_maker=...).inference(prompt).
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        prompt = build_ambiguity_prompt(q, schema_summary, data_source_hint)
        raw = (
            LLM(resolved_model, usage_session_maker=async_session_maker).inference(
                prompt,
                usage_scope="ambiguity_gate",
            )
            or ""
        ).strip()

        # 5. Parse strict JSON -> contract shape; junk -> not-ambiguous.
        return _parse_ambiguity(raw)
    except Exception as e:  # never break the request path
        logger.warning("ambiguity_gate detect_ambiguity failed: %s", e)
        return _safe_result()
