"""Generate 3 grounded FOLLOW-UP questions after a chat answer, PER-AGENT.

After a Studio chat answer, this proposes the questions a user would most
likely ask NEXT — grounded in the user's QUESTION + the assistant's ANSWER,
plus a light list of the studio's pinned table names for grounding. The prompt
is kept deliberately small (no full schema / column values / voice /
instructions dump) so the single small-model inference returns fast.

Reuse, not reinvention (CLAUDE.md HARD RULES) — clones the idiom of the sibling
``auto_queries.py`` exactly:
  * LLM = org small default model via ``LLMService().get_default_model(...,
    is_small=True)``, called through dash's one-shot wrapper
    ``LLM(model, usage_session_maker=async_session_maker).inference(prompt,
    usage_scope="followups")`` (SYNC -> run in a worker thread).
  * Schema digest = ``knowledge_proposer._introspect_schema_text``.
  * Tolerant fence-strip + JSON parse (``_strip_fences`` /
    ``_parse_followup_list``).

Design rules honored: flag-gated (``flags.FOLLOWUPS``, default OFF -> no-op);
cheap tier (ONE small-model inference); NEVER raises into the caller; writes
NOTHING (read-only generator).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.brain.knowledge_proposer import _introspect_schema_text
from app.settings.hybrid_flags import flags
from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# How many pinned sources to introspect for light table-name grounding.
_MAX_SCHEMA_SOURCES = 3
# Cap on how many table names go into the prompt (light context only — the
# follow-up suggester needs the Q + A, not a full schema dump).
_MAX_TABLE_NAMES = 20
# Hard cap on each follow-up question's length.
_MAX_Q_CHARS = 120


def _clean(s: Any) -> str:
    return str(s).strip() if s is not None else ""


def _strip_fences(text: str) -> str:
    """Strip ```json ... ``` / ``` ... ``` fences a model may wrap output in."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _parse_followup_list(text: str) -> List[str]:
    """Parse the LLM output into a list of follow-up question strings.

    Tolerant: the model may return a JSON array of strings OR an array of
    objects with a "question" key; falls back to the first ``[...]`` block.
    Dedupes case-insensitively, caps length, returns [] on junk (never raises).
    """
    raw = _strip_fences(text)
    candidates: List[Any] = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            candidates = parsed
        elif isinstance(parsed, dict):
            candidates = parsed.get("followups") or parsed.get("questions") or []
    except Exception:
        m = re.search(r"\[.*\]", raw, flags=re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
                candidates = parsed if isinstance(parsed, list) else []
            except Exception:
                candidates = []

    out: List[str] = []
    seen: set = set()
    for c in candidates:
        if isinstance(c, str):
            q = _clean(c)
        elif isinstance(c, dict):
            q = _clean(c.get("question") or c.get("followup") or c.get("text"))
        else:
            q = ""
        if not q:
            continue
        # Strip a leading "1. " / "- " numbering the model may sneak in.
        q = re.sub(r"^\s*(?:\d+[\.\)]|[-*])\s*", "", q).strip()
        if not q:
            continue
        if len(q) > _MAX_Q_CHARS:
            q = q[:_MAX_Q_CHARS].rstrip()
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def _build_prompt(question: str, answer: str, table_names: str) -> str:
    """Lean one-shot prompt asking for EXACTLY 3 short follow-up questions.

    Deliberately tiny: a follow-up suggestion only needs the user's question,
    the assistant's answer, and (optionally) the table names to stay grounded.
    Heavier context (full schema, column values, voice, instructions, policy)
    is intentionally omitted to keep the small-model inference fast, and the
    "EXACTLY 3, <= ~90 chars each" instruction caps the output length.
    """
    parts: List[str] = [
        "A user just received an answer in a chat about their data. Propose the "
        "3 follow-up QUESTIONS the user is most likely to ask NEXT.",
        "",
        "Each follow-up MUST:",
        "- build on the question + answer (drill down, compare, trend over time, "
        "segment, or check data quality),",
        "- be ONE concise natural-language question (<= ~90 characters),",
        "- have no numbering, no preamble, no explanation.",
    ]
    if table_names:
        parts += [
            "",
            f"Tables available (ground on these; do NOT invent others): {table_names}",
        ]
    parts += [
        "",
        f"Question:\n{question or '(not provided)'}",
        "",
        f"Answer:\n{answer or '(not provided)'}",
        "",
        "Return ONLY a single JSON array of EXACTLY 3 short strings (no prose, no "
        'markdown), e.g.:',
        '["First follow-up question?", "Second follow-up question?", "Third follow-up question?"]',
    ]
    return "\n".join(parts)


def _default_infer(model: Any):
    """Build the default SYNC one-shot inference callable (OpenRouter-only)."""
    def infer(prompt: str) -> str:
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        return LLM(model, usage_session_maker=async_session_maker).inference(
            prompt, usage_scope="followups"
        )

    return infer


def _shorten(s: Any, n: int = 70) -> str:
    """Trim a finding fragment to a chip-friendly length (no trailing punctuation)."""
    t = _clean(s).rstrip(".!?, ")
    return (t[: n - 1].rstrip() + "…") if len(t) > n else t


async def _seed_followups_from_sense_making(
    db: AsyncSession, report_id: str, existing: List[str]
) -> List[str]:
    """PREPEND 1-2 follow-up chips derived from the stored sense_making findings.

    Reuses the already-persisted card (NO LLM). Self-gates on ``flags.SENSE_MAKING``
    (OFF → unchanged). Each chip is concise (<90 chars), and the merged list is
    de-duplicated case-insensitively. NEVER raises (caller also guards)."""
    if not getattr(flags, "SENSE_MAKING", False):
        return existing
    try:
        from app.ai.knowledge.sense_maker import get_stored_sense_making

        sm = await get_stored_sense_making(db, report_id)
        if not isinstance(sm, dict):
            return existing
        findings = [f for f in (sm.get("findings") or []) if isinstance(f, dict)]
        if not findings:
            return existing

        chips: List[str] = []
        for f in findings[:2]:
            what = _shorten(f.get("what"), 60)
            if what:
                chips.append(f"Why did {what} happen?")
            nw = f.get("now_what")
            action = _shorten(nw.get("action"), 60) if isinstance(nw, dict) else ""
            if action:
                chips.append(f"Drill into: {action}")

        # Keep at most 2 derived chips; bound each to <90 chars.
        chips = [c[:89].rstrip() if len(c) > 89 else c for c in chips][:2]
        if not chips:
            return existing

        merged: List[str] = []
        seen: set = set()
        for q in chips + list(existing):
            q = _clean(q)
            if not q:
                continue
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(q)
        return merged
    except Exception:  # noqa: BLE001
        return existing


async def generate_followups(
    db: AsyncSession,
    *,
    organization,
    current_user,
    report_id: str,
    answer_text: str = "",
    question_text: str = "",
    model=None,
    max_n: int = 4,
) -> dict:
    """Generate 3 grounded follow-up questions for a report's last answer.

    Grounded in the user's question + the assistant's answer, plus a light list
    of the table names from the studio's pinned sources (or the report's own
    data sources when there's no studio). Kept small for a fast small-model call.

    Self-gates on ``flags.FOLLOWUPS`` (default OFF -> ``{disabled:True}``).
    NEVER raises: any soft failure returns ``{"ok": False, "error": ...,
    "followups": []}``.
    """
    if not getattr(flags, "FOLLOWUPS", False):
        return {"disabled": True, "followups": []}

    try:
        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return {"ok": False, "error": "no organization", "followups": []}

        try:
            max_n = int(max_n)
        except Exception:
            max_n = 4
        max_n = max(1, min(max_n, 6))

        # 1. Load the report (org-scoped).
        from app.models.report import Report

        res = await db.execute(
            select(Report).where(
                Report.id == report_id,
                Report.organization_id == org_id,
            )
        )
        report = res.scalar_one_or_none()
        if report is None:
            return {"ok": False, "error": "report not found", "followups": []}

        studio_id = getattr(report, "studio_id", None)
        source = "studio" if studio_id else "report"

        ds_rows: List[Any] = []

        # 2. Resolve the data sources to ground on — LIGHT table-name context
        #    only (no full schema / column values / voice / instructions /
        #    policy; a follow-up suggestion just needs the Q + A + table names).
        if studio_id:
            from app.models.studio import StudioDataSource

            try:
                from app.models.data_source import DataSource

                dres = await db.execute(
                    select(StudioDataSource).where(
                        StudioDataSource.studio_id == studio_id,
                        StudioDataSource.deleted_at.is_(None),
                    )
                )
                agent_ids = [p.agent_id for p in dres.scalars().all()]
                if agent_ids:
                    sd = await db.execute(
                        select(DataSource).where(
                            DataSource.id.in_(agent_ids),
                            DataSource.organization_id == org_id,
                        )
                    )
                    ds_rows = list(sd.scalars().all())
            except Exception:
                ds_rows = []
        else:
            # 3. No studio -> use the report's own data sources (best-effort).
            try:
                ds_rows = list(getattr(report, "data_sources", None) or [])
            except Exception:
                ds_rows = []

        # Light table-name context (cap a few sources / a handful of names).
        table_names: List[str] = []
        for ds in ds_rows[:_MAX_SCHEMA_SOURCES]:
            try:
                _schema_text, names = _introspect_schema_text(ds)
            except Exception:
                names = set()
            for n in (names or []):
                n = _clean(n)
                if n and n not in table_names:
                    table_names.append(n)
        table_names_text = ", ".join(table_names[:_MAX_TABLE_NAMES])

        # 4. Best-effort fill of answer/question from the latest completion.
        if not _clean(answer_text):
            try:
                from app.models.completion import Completion

                cres = await db.execute(
                    select(Completion)
                    .where(
                        Completion.report_id == report_id,
                        Completion.role.in_(["system", "ai_agent"]),
                    )
                    .order_by(Completion.created_at.desc())
                )
                comp = cres.scalars().first()
                if comp is not None:
                    raw = getattr(comp, "completion", None)
                    if raw is None:
                        raw = getattr(comp, "content", None)
                    if isinstance(raw, dict):
                        raw = raw.get("content") or raw.get("answer") or json.dumps(raw)
                    answer_text = _clean(raw)
            except Exception:
                pass

        question = _clean(question_text)
        answer = _clean(answer_text)

        # 5. Resolve the org small default model once if not provided.
        if model is None:
            try:
                from app.services.llm_service import LLMService

                model = await LLMService().get_default_model(
                    db, organization, current_user, is_small=True
                )
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"no model: {e}", "followups": []}
        if model is None:
            return {"ok": False, "error": "no default model", "followups": []}

        # 6. ONE small-model inference (SYNC -> worker thread).
        infer = _default_infer(model)
        try:
            prompt = _build_prompt(question, answer, table_names_text)
            raw = await asyncio.to_thread(infer, prompt)
        except Exception as e:  # noqa: BLE001
            logger.warning("followups inference failed for %s: %s", report_id, e)
            return {"ok": False, "error": f"llm error: {e}", "followups": []}

        followups = _parse_followup_list(raw or "")[:max_n]

        # Sense-Making seeding (flag-gated, fail-soft): PREPEND 1-2 chips derived
        # from the top stored findings so the user can act on the decision layer.
        # No sm / flag OFF / any error → existing suggestions returned unchanged.
        try:
            followups = await _seed_followups_from_sense_making(
                db, report_id, followups
            )
        except Exception:  # noqa: BLE001 — never alter the happy path on error
            pass

        return {"ok": True, "followups": followups, "source": source}

    except Exception as e:  # noqa: BLE001 - never raise into the caller
        logger.warning("generate_followups failed: %s", e)
        return {"ok": False, "error": str(e), "followups": []}
