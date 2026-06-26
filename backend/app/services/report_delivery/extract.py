"""Pull STRUCTURED pieces out of a finished report and SANITIZE the agent's chat
prose for email.

The agent's stored completion text is written for the in-app chat UI: it carries
planning markers (``**🧠 Planning ✓**``), references to widgets rendered
elsewhere ("the table generated above"), fenced tool code, and a quick
human-readable recap table that is *not* the real data. Inlining that verbatim
into an email is the bug this layer fixes — the accurate data lives in
``steps.data``; the prose is only good for an intro + insight bullets, and only
after cleaning.

All functions are pure or read-only; nothing here sends mail.
"""
from __future__ import annotations

import json
import re
from typing import Optional

# ---- sanitize -------------------------------------------------------------

_PLANNING_RE = re.compile(r"\*\*\s*🧠[^*]*\*\*\s*")          # **🧠 Planning (unknown) ✓**
_CODE_FENCE_RE = re.compile(r"```.*?```", re.S)               # ``` … ``` tool code
_GENERATE_DF_RE = re.compile(r"def\s+generate_df\b.*", re.S)  # raw python wrapper tail
_ABOVE_RE = re.compile(r"\s*\(?\s*\b(?:full detail (?:is )?visible in the )?(?:interactive )?table (?:has been )?(?:generated |shown )?(?:above|below)[^.)\n]*\)?\.?", re.I)
_MD_TABLE_RE = re.compile(r"(?:^\|.*\|[ \t]*\n)+", re.M)       # a markdown pipe table block
_HEADING_EMOJI_RE = re.compile(r"^#{1,6}\s*[^\w\s]*\s*", re.M)  # ## 🎵 heading → strip markers


def sanitize_chat_content(text: Optional[str]) -> str:
    """Strip chat-UI artefacts so the remaining prose is safe to email.

    Removes: planning markers, fenced code / generate_df wrappers, "see table
    above" UI references, the agent's fuzzy recap markdown table (the real table
    is rendered from ``steps.data`` separately), and stray heading emoji/markers.
    """
    if not text:
        return ""
    t = text
    t = _PLANNING_RE.sub("", t)
    t = _CODE_FENCE_RE.sub("", t)
    t = _GENERATE_DF_RE.sub("", t)
    t = _MD_TABLE_RE.sub("", t)          # drop the prose recap table
    t = _ABOVE_RE.sub("", t)
    t = _HEADING_EMOJI_RE.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t)     # collapse blank runs
    t = re.sub(r"-{3,}", "", t)          # stray markdown rules
    return t.strip()


# ---- split prose into intro + insight bullets -----------------------------

def split_intro_and_insights(narrative: str) -> tuple[str, list[tuple[str, str]]]:
    """From sanitized prose, return (intro_paragraph, [(title, body), ...]).

    Intro = the first non-empty paragraph (minus any 'I'll query …' preamble).
    Insights = bold-led points from the 'Analysis' section if present, else any
    ``N. **Title** body`` / ``**Title** body`` points found. Both already
    sanitized; markdown bold becomes <b>.
    """
    text = narrative or ""
    # drop a leading "I'll query …" planning sentence
    text = re.sub(r"^\s*I['’]ll\s+query[^.\n]*\.\s*", "", text, flags=re.I)

    seg = text
    m = re.search(r"\bAnalysis\b", seg)
    insight_seg = seg[m.end():] if m else seg
    insight_seg = re.split(r"\bQuery Result\b", insight_seg)[0]

    insights: list[tuple[str, str]] = []
    for mm in re.finditer(
        r"\*\*(.+?)\*\*\s*\n?(.*?)(?=\n\s*\d+\.\s*\*\*|\n\s*\*\*|\Z)", insight_seg, re.S
    ):
        title = re.sub(r"\*\*", "", mm.group(1)).strip().rstrip(":")
        body = " ".join(mm.group(2).split())
        body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
        if title and len(body) > 15:
            insights.append((title, body))

    # intro = first paragraph that isn't itself a bold-led insight header
    intro = ""
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p:
            continue
        if p.startswith("**") and "Analysis" not in p:
            continue
        intro = " ".join(p.split())
        break
    intro = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", intro)
    return intro, insights


# ---- structured result from steps.data ------------------------------------

async def extract_result(report_id: str) -> Optional[dict]:
    """Latest executed step for the report → {columns, rows, sql} or None.

    Reads ``steps.data`` (the real result grid) + ``steps.code`` (the SQL, with
    the clean SELECT lifted out of any python wrapper). Read-only.
    """
    from sqlalchemy import select, desc
    from app.dependencies import async_session_maker
    from app.models.step import Step
    from app.models.widget import Widget

    async with async_session_maker() as db:
        wids = [
            w.id for w in (
                await db.execute(select(Widget).where(Widget.report_id == report_id))
            ).scalars().all()
        ]
        if not wids:
            return None
        steps = (
            await db.execute(
                select(Step).where(Step.widget_id.in_(wids)).order_by(desc(Step.created_at)).limit(25)
            )
        ).scalars().all()
        for s in steps:
            if s.data and (s.code or s.query_id):
                return _normalize_result(s.data, s.code)
    return None


def _normalize_result(data, code) -> Optional[dict]:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None
    rows = cols = None
    if isinstance(data, dict):
        cols = data.get("columns") or data.get("schema")
        rows = data.get("rows") or data.get("data")
        if isinstance(cols, list) and cols and isinstance(cols[0], dict):
            cols = [c.get("field") or c.get("name") or c.get("headerName") for c in cols]
    elif isinstance(data, list):
        rows = data
        if rows and isinstance(rows[0], dict):
            cols = list(rows[0].keys())
    if not rows:
        return None
    if not cols and isinstance(rows[0], dict):
        cols = list(rows[0].keys())

    sql = None
    if code:
        m = re.search(r'"""\s*(SELECT.*?)\s*"""', code, re.S | re.I) or re.search(
            r"'''\s*(SELECT.*?)\s*'''", code, re.S | re.I
        )
        if m:
            sql = m.group(1).strip()
        elif re.match(r"\s*SELECT\b", code, re.I):
            sql = code.strip()
    return {"columns": cols or [], "rows": rows, "sql": sql}


# ---- latest agent narrative -----------------------------------------------

async def latest_narrative(report_id: str) -> str:
    """Newest AI completion text for the report, raw (un-sanitized)."""
    from sqlalchemy import select, desc
    from app.dependencies import async_session_maker
    from app.models.completion import Completion

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(Completion).where(Completion.report_id == report_id)
                .order_by(desc(Completion.created_at)).limit(6)
            )
        ).scalars().all()
        for c in rows:
            comp = c.completion
            t = comp.get("content") if isinstance(comp, dict) else (comp if isinstance(comp, str) else None)
            if t and isinstance(t, str) and t.strip():
                return t
    return ""
