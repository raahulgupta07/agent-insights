"""Phase 4a — "Analysis Notebook" (Julius-style show-your-work).

Assembles a step-by-step narrative of an analysis run from the persisted
``Step`` rows, exposed READ-ONLY. Each meaningful step becomes a plain-language
entry: what the step did + a short result summary (row count + a deterministic
one-liner when a DataFrame reconstructs). NO raw code dump, NO LLM call.

Public surface
--------------
    async def build_analysis_notebook(db, *, report_id, completion_id=None) -> dict | None

Returns ``{"enabled": True, "headline": <str?>, "steps": [...]}`` or, when the
flag is off, ``None`` (the route maps that to ``{"enabled": False, ...}``).

Design rules
------------
- Flag-gated: ``flags.ANALYSIS_NOTEBOOK`` off → ``None`` (feature invisible).
- Read-only DB reads of ``Step`` (via its ``Widget.report_id`` link).
- Fail-soft: ANY error → ``None`` (logged at debug). NEVER raises.
- No new dependency, no migration.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Steps in these states carry no analysis worth narrating.
_SKIP_STATUSES = {"draft", "error", "failed", "cancelled"}
# Cap a "did"/"result" one-liner so a notebook entry stays scannable.
_LINE_CAP = 240


def _first_sentence(text: str, cap: int = _LINE_CAP) -> str:
    """Trim to a single clean line (first sentence-ish, hard-capped)."""
    s = " ".join(str(text or "").split())
    if not s:
        return ""
    for sep in (". ", "\n"):
        idx = s.find(sep)
        if 0 < idx <= cap:
            s = s[:idx]
            break
    if len(s) > cap:
        s = s[: cap - 3].rstrip() + "..."
    return s


def _summarize_did(step: Any) -> str:
    """Plain one-line description of what the step DID — no raw code dump.

    Prefer the step's own ``description``; else summarize its ``prompt`` (the
    natural-language ask that produced the code); else fall back to the title.
    """
    desc = _first_sentence(getattr(step, "description", "") or "")
    if desc:
        return desc
    prompt = _first_sentence(getattr(step, "prompt", "") or "")
    if prompt:
        return f"Ran an analysis to {prompt[0].lower()}{prompt[1:]}" if prompt else prompt
    title = _first_sentence(getattr(step, "title", "") or "")
    return title or "Ran an analysis step"


def _summarize_result(step: Any) -> str:
    """Short result summary: row count + a deterministic insight one-liner when a
    DataFrame reconstructs from the step's data; else the step description."""
    try:
        from app.ai.knowledge.sense_maker import _df_from_step_data

        df = _df_from_step_data(getattr(step, "data", None))
    except Exception:
        df = None

    if df is not None:
        try:
            n_rows = int(len(df))
            n_cols = int(len(df.columns))
            base = f"{n_rows} row{'s' if n_rows != 1 else ''} × {n_cols} column{'s' if n_cols != 1 else ''}"
        except Exception:
            base = "returned a result"
        try:
            from app.ai.knowledge.insights import compute_insights

            insights = compute_insights(df) or []
            msgs = [str((i or {}).get("message") or "").strip() for i in insights[:2]]
            note = " ".join(m for m in msgs if m)
            if note:
                return _first_sentence(f"{base} — {note}")
        except Exception:
            pass
        return base

    desc = _first_sentence(getattr(step, "description", "") or "")
    return desc or "No tabular result."


async def build_analysis_notebook(
    db, *, report_id: str, completion_id: Optional[str] = None
) -> "dict | None":
    """Build a step-by-step analysis notebook for a report run. See module docstring."""
    try:
        from app.settings.hybrid_flags import flags

        if not flags.ANALYSIS_NOTEBOOK:
            return None

        from sqlalchemy import select, asc
        from app.models.step import Step
        from app.models.widget import Widget

        # Steps link to a report through Widget.report_id (Step -> Widget).
        stmt = (
            select(Step)
            .join(Widget, Step.widget_id == Widget.id)
            .where(Widget.report_id == report_id, Step.deleted_at.is_(None))
            .order_by(asc(Step.created_at))
        )
        if completion_id:
            from app.models.completion import Completion

            stmt = stmt.where(
                Step.id.in_(
                    select(Completion.step_id).where(
                        Completion.id == completion_id,
                        Completion.step_id.isnot(None),
                    )
                )
            )

        steps = (await db.execute(stmt)).scalars().all()
        if not steps:
            return {"enabled": True, "steps": []}

        entries: List[Dict[str, Any]] = []
        for step in steps:
            try:
                status = (getattr(step, "status", "") or "").lower()
                if status in _SKIP_STATUSES:
                    continue
                # Skip empty steps (no code, no result, no description).
                if not any(
                    str(getattr(step, k, "") or "").strip()
                    for k in ("code", "description", "prompt")
                ) and not getattr(step, "data", None):
                    continue

                title = _first_sentence(getattr(step, "title", "") or "", cap=120) or (
                    f"Step {len(entries) + 1}"
                )
                chart = getattr(step, "type", None)
                entries.append(
                    {
                        "n": len(entries) + 1,
                        "title": title,
                        "did": _summarize_did(step),
                        "result": _summarize_result(step),
                        "chart": chart if chart and chart != "table" else None,
                    }
                )
            except Exception:
                continue

        headline: Optional[str] = None
        if entries:
            headline = f"Analysis ran in {len(entries)} step{'s' if len(entries) != 1 else ''}."

        return {"enabled": True, "headline": headline, "steps": entries}
    except Exception:
        logger.debug("notebook: build_analysis_notebook failed", exc_info=True)
        return None
