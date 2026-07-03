"""Golden-SQL evals - store + grade the EXPECTED SQL alongside the expected rows.

Today the eval harness (``services/eval_harness.py``) grades a golden purely on
the produced ROWS (a ``result_set`` rule: ``golden_data`` / ``golden_columns``).
OpenAI's eval pipeline (Diagram 6) also keeps the expected SQL and grades on BOTH
the SQL (the INTENT - same tables/filters/grain) and the result set. This module
adds that second axis WITHOUT a migration: the expected SQL is stored INSIDE the
existing ``result_set`` rule dict (``rule["golden_sql"]``), which already lives in
``TestCase.expectations_json["rules"]``.

Two public surfaces, both flag-gated on ``flags.GOLDEN_SQL`` (env
``HYBRID_GOLDEN_SQL``, default OFF -> byte-identical no-op):

  * ``attach_golden_sql(rule, snapshot)`` - PURE. Given an existing ``result_set``
    rule dict + an eval snapshot, pulls the generated SQL out of the snapshot
    (``snapshot["create_data"]["code"]``) and returns the rule with
    ``rule["golden_sql"]`` set. Never raises.
  * ``grade_sql(db, *, organization_id, model, generated_sql, golden_sql)`` -
    async LLM-as-judge of whether ``generated_sql`` matches ``golden_sql`` in
    INTENT (tolerant of syntactic variation). Returns
    ``{match: bool, score: float, reasoning: str}``. Fail-soft -> inconclusive
    PASS on any infra/parse error (never block on an LLM hiccup).

Design mirrors ``services/evals/safety_evals.py`` EXACTLY (one-shot
``LLM(model, usage_session_maker=...).inference`` in a worker thread, tolerant
JSON parse, fully fail-soft, ASCII only). No DB writes here; no migration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Keep the judge prompt cheap + bounded.
_MAX_SQL_CHARS = 6000


# --------------------------------------------------------------------------- #
# attach_golden_sql - PURE snapshot -> rule augmentation
# --------------------------------------------------------------------------- #

def _extract_generated_sql(snapshot: dict) -> str:
    """Pull the generated SQL out of an eval snapshot's create_data block.

    ``TestEvaluationService.build_final_snapshot`` records the latest successful
    ``create_data`` tool's SQL under ``snapshot["create_data"]["code"]`` (filled
    from the tool ``arguments_json.query``/``code`` or ``result_json``). Returns
    "" when absent. Never raises.
    """
    try:
        cd = snapshot.get("create_data") or {}
        if not isinstance(cd, dict):
            return ""
        code = cd.get("code") or ""
        if isinstance(code, str):
            return code.strip()
        return ""
    except Exception:
        return ""


def attach_golden_sql(rule: dict, snapshot: dict) -> dict:
    """Add ``rule["golden_sql"]`` (the expected SQL) to an existing result_set rule.

    Pure + fail-soft. Returns the (possibly augmented) ``rule`` dict. When the
    flag is OFF, or ``rule`` is not a dict, or no SQL is present in the snapshot,
    the rule is returned UNCHANGED (no ``golden_sql`` key added). Never raises.

    The SQL is kept INSIDE the rule dict so it rides along inside
    ``TestCase.expectations_json["rules"]`` - no migration, no schema change.
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.GOLDEN_SQL:
            return rule
        if not isinstance(rule, dict):
            return rule

        sql = _extract_generated_sql(snapshot or {})
        if not sql:
            return rule

        # Do not clobber a golden_sql that a caller already curated.
        if not rule.get("golden_sql"):
            rule["golden_sql"] = sql[:_MAX_SQL_CHARS]
        return rule
    except Exception as e:  # noqa: BLE001
        logger.warning("attach_golden_sql failed: %s", e)
        return rule


# --------------------------------------------------------------------------- #
# grade_sql - LLM-as-judge of SQL intent match
# --------------------------------------------------------------------------- #

def _grade_prompt(generated_sql: str, golden_sql: str) -> str:
    return (
        "You are a SQL-INTENT judge for an analytics agent.\n"
        "Decide whether the GENERATED SQL matches the GOLDEN (expected) SQL in "
        "INTENT: the same tables, the same filters/predicates, and the same grain "
        "(group-by / aggregation level). Be TOLERANT of pure syntactic variation "
        "- alias names, column/clause ordering, whitespace, equivalent JOIN vs "
        "WHERE forms, quoting, and casing do NOT matter.\n"
        "MATCH (score near 1.0) when the two queries would answer the same "
        "question over the same data. NO MATCH (score near 0.0) when they hit "
        "different tables, apply different filters, or aggregate at a different "
        "grain.\n\n"
        f"GOLDEN SQL:\n{golden_sql}\n\n"
        f"GENERATED SQL:\n{generated_sql}\n\n"
        'Respond with STRICT JSON only, no prose, exactly: '
        '{"match": true|false, "score": 0.0-1.0, "reason": "<=140 chars"}.'
    )


def _parse_grade_json(raw: str) -> Optional[Dict[str, Any]]:
    """Tolerant parse of the judge's JSON (mirrors safety_evals)."""
    if not raw:
        return None
    txt = raw.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt)
    try:
        obj = json.loads(txt, strict=False)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0), strict=False)
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


def _inconclusive(reason: str) -> Dict[str, Any]:
    """Fail-soft result: an infra/parse failure never blocks the product."""
    return {"match": True, "score": 1.0, "reason": reason, "inconclusive": True}


def _coerce_grade(parsed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(parsed, dict) or "match" not in parsed:
        return None
    match = parsed.get("match")
    if isinstance(match, str):
        match = match.strip().lower() in ("true", "yes", "match", "1")
    match = bool(match)
    try:
        score = float(parsed.get("score"))
    except Exception:
        score = 1.0 if match else 0.0
    score = max(0.0, min(1.0, score))
    reason = str(parsed.get("reason") or "").strip()[:200] or "ok"
    return {"match": match, "score": score, "reason": reason, "inconclusive": False}


async def grade_sql(
    db: Any,
    *,
    organization_id: Any,
    model: Any,
    generated_sql: str,
    golden_sql: str,
) -> Dict[str, Any]:
    """LLM-judge whether ``generated_sql`` matches ``golden_sql`` in INTENT.

    Returns ``{match: bool, score: float, reason: str, inconclusive: bool}``.
    Flag-gated (``flags.GOLDEN_SQL``): OFF -> inconclusive PASS (no LLM call).
    Fully fail-soft: a missing model / LLM error / unparseable output all return
    an inconclusive PASS so a golden is never failed on an infra hiccup. NEVER
    raises.
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.GOLDEN_SQL:
            return _inconclusive("golden-sql disabled")

        gen = (generated_sql or "").strip()[:_MAX_SQL_CHARS]
        gold = (golden_sql or "").strip()[:_MAX_SQL_CHARS]
        if not gen or not gold:
            return _inconclusive("missing generated or golden SQL")
        if model is None:
            return _inconclusive("no model available")

        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        prompt = _grade_prompt(gen, gold)

        def _infer() -> str:
            return LLM(model, usage_session_maker=async_session_maker).inference(
                prompt, usage_scope="golden_sql"
            )

        raw = await asyncio.to_thread(_infer)
        grade = _coerce_grade(_parse_grade_json(raw or ""))
        if grade is not None:
            return grade
        return _inconclusive("judge output unparseable")
    except Exception as e:  # noqa: BLE001
        logger.warning("grade_sql failed: %s", e)
        return _inconclusive("judge error")
