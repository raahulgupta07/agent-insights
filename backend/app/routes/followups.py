"""Suggested follow-up questions after a chat answer (per-agent).

ONE route: ``POST /api/reports/{report_id}/followups`` — given the just-answered
question + answer (passed from the front-end), asks the org's small model for a
few SHORT follow-up questions a user would likely ask next, grounded in the
report's Studio (voice + active instructions + an optional ``followup_policy``
artifact) and the pinned sources' real schema. Returns a plain list of strings
the chat renders as clickable chips.

The work is in ``app.ai.knowledge.followups.generate_followups`` which self-gates
on ``flags.FOLLOWUPS`` (default OFF -> ``{"disabled": True, "followups": []}``)
and NEVER raises -> this route never 500s.

Auth mirrors ``app.routes.completion``: report-scoped, ``create_reports``
permission, org-scoped. The report's org-membership is enforced by loading the
Report under the caller's organization.

LANDMINE (intentional): NO ``from __future__ import annotations`` here. With a
permission-decorated endpoint, stringized body annotations make FastAPI mis-read
the pydantic/dict body as a query param (422). The body is optional and accepted
as ``body: dict = Body(default={})``.
"""

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError
from app.ai.knowledge.followups import generate_followups
from app.models.organization import Organization
from app.models.report import Report
from app.models.user import User

router = APIRouter(tags=["completions"])


@router.post("/api/reports/{report_id}/followups")
@requires_permission('create_reports')
async def suggest_followups(
    report_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db),
):
    """Return up to N suggested follow-up questions for a report's last answer.

    Body (all optional): ``{"answer_text": str, "question_text": str,
    "max_n": int}``. Returns ``{"ok": True, "followups": [...], "source": ...}``;
    ``{"disabled": True, "followups": []}`` when the FOLLOWUPS flag is OFF;
    ``{"ok": False, "error": ..., "followups": []}`` on a soft failure. Never 500s.
    """
    # Enforce org-scoped report access (404 if not in the caller's org).
    res = await db.execute(
        select(Report).where(
            Report.id == report_id,
            Report.organization_id == organization.id,
        )
    )
    if res.scalar_one_or_none() is None:
        raise AppError.not_found("report.not_found", "Report not found")

    body = body if isinstance(body, dict) else {}
    answer_text = str(body.get("answer_text") or "")
    question_text = str(body.get("question_text") or "")
    try:
        max_n = int(body.get("max_n", 4))
    except Exception:
        max_n = 4

    return await generate_followups(
        db,
        organization=organization,
        current_user=current_user,
        report_id=report_id,
        answer_text=answer_text,
        question_text=question_text,
        max_n=max_n,
    )
