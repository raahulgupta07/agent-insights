"""Per-agent (Studio) scheduled reports — hybrid P2.

Surfaces the existing ScheduledPrompt engine as a studio-scoped API so each
Studio (= agent) can own its own scheduled reports. Everything here is gated on
``flags.AGENT_REPORTS`` (HYBRID_AGENT_REPORTS, default OFF, ON for org
55278108) and returns 404 when the flag is off, so a fresh deploy behaves
exactly like upstream.

Auth mirrors external_platform.py per-agent routes: owner/editor (via
``resolve_studio_access``) may manage; any role with access may list.

How a scheduled report binds to a report_id
--------------------------------------------
A ScheduledPrompt has a NOT-NULL ``report_id``. Rather than make the user pick a
report, every Studio gets ONE lazily-created hidden "container" Report bound to
``studio_id`` (title sentinel ``__scheduled_reports__``). All of that studio's
scheduled prompts hang off this single container report, which means:
  * the existing ``ScheduledPromptService.list_scheduled_prompts(report_id)``
    and ``scheduled_run_prompt`` code paths work unchanged (no scheduling
    reimplemented here), and
  * runs execute against a real report owned by the studio, so the agent's
    pinned sources / SMTP identity apply automatically.
The container is created on first schedule (``_get_or_create_container_report``)
and reused thereafter. We never expose it as a normal report (sentinel title +
``status='archived'``). Chosen over "attach to an existing chat report" because
scheduled reports are agent-level config, not tied to one conversation.

The optional ``format`` (auto|table|dashboard) is stashed inside the
ScheduledPrompt.prompt JSON dict (no column → no migration), alongside an
optional ``title`` for display.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.models.user import User
from app.models.organization import Organization
from app.models.report import Report
from app.models.scheduled_prompt import ScheduledPrompt
from app.schemas.scheduled_prompt_schema import (
    ScheduledPromptCreate,
    ScheduledPromptUpdate,
)
from app.schemas.notification_schema import NotificationSubscriber
from app.services.scheduled_prompt_service import scheduled_prompt_service
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studio_reports"])

# Durable marker for the per-studio hidden container report. We tag it on
# ``report_type`` (a stable, indexed column) rather than ``title`` because the
# completion run AUTO-RETITLES the report from the conversation (e.g.
# "__scheduled_reports__" -> "Top 10 Artists by Revenue") — so any title-based
# lookup breaks on the second run (BUG 1). report_type is never touched by the
# titler, so the container stays findable and the get-or-create stays idempotent.
_CONTAINER_TYPE = "scheduled_container"
_CONTAINER_TITLE = "Scheduled reports"  # display title only; not used for lookup
_ALLOWED_FORMATS = ("auto", "table", "dashboard")


# ---------------------------------------------------------------------------
# Request / response shapes (kept local — these are the studio-facing wrappers
# around the existing ScheduledPrompt service).
# ---------------------------------------------------------------------------
class StudioReportCreate(BaseModel):
    prompt_content: str = Field(..., min_length=1)
    cron_schedule: str
    subscribers: Optional[List[NotificationSubscriber]] = None
    format: str = Field(default="auto")
    title: Optional[str] = None
    is_active: Optional[bool] = True


class StudioReportUpdate(BaseModel):
    prompt_content: Optional[str] = None
    cron_schedule: Optional[str] = None
    subscribers: Optional[List[NotificationSubscriber]] = None
    format: Optional[str] = None
    title: Optional[str] = None
    is_active: Optional[bool] = None


def _normalize_format(fmt: Optional[str]) -> str:
    fmt = (fmt or "auto").lower().strip()
    return fmt if fmt in _ALLOWED_FORMATS else "auto"


def _serialize(sp: ScheduledPrompt) -> dict:
    prompt = sp.prompt or {}
    return {
        "id": str(sp.id),
        "title": prompt.get("title") or "Scheduled report",
        "prompt_content": prompt.get("content") or "",
        "format": _normalize_format(prompt.get("format")),
        "cron_schedule": sp.cron_schedule,
        "subscribers": sp.notification_subscribers or [],
        "is_active": bool(sp.is_active),
        "last_run_at": sp.last_run_at,
        "created_at": sp.created_at,
        "updated_at": sp.updated_at,
    }


async def _require_report_manager(db: AsyncSession, studio_id: str, user) -> str:
    """Owner/editor only for managing scheduled reports. Raises 403 otherwise."""
    role = await resolve_studio_access(db, studio_id, user)
    if role not in ("owner", "editor"):
        raise HTTPException(status_code=403, detail="You do not have access to manage this agent's reports.")
    return role


async def _load_studio(db: AsyncSession, studio_id: str, organization):
    from app.models.studio import Studio
    result = await db.execute(
        select(Studio).where(
            Studio.id == studio_id,
            Studio.organization_id == organization.id,
            Studio.deleted_at.is_(None),
        )
    )
    studio = result.scalar_one_or_none()
    if not studio:
        raise HTTPException(status_code=404, detail="Agent not found")
    return studio


async def _find_container_report(db: AsyncSession, studio, organization) -> Optional[Report]:
    """Return this studio's container report (by stable report_type), or None.

    Matches on report_type (not title) so a run-now auto-retitle can't hide it.
    """
    result = await db.execute(
        select(Report)
        .where(
            Report.studio_id == studio.id,
            Report.organization_id == organization.id,
            Report.report_type == _CONTAINER_TYPE,
            Report.deleted_at.is_(None),
        )
        .order_by(Report.created_at.asc())
    )
    return result.scalars().first()


async def _get_or_create_container_report(
    db: AsyncSession,
    studio,
    current_user: User,
    organization: Organization,
) -> Report:
    """Idempotent get-or-create of the hidden per-studio scheduled-reports container.

    Creation goes through ``report_service.create_report`` with ``studio_id`` set
    so the container inherits the studio's PINNED data sources exactly like a
    normal studio chat report — otherwise the scheduled agent run has no data
    context and returns prose only / "data source unavailable" (BUG 2). We then
    tag report_type/status on the freshly-created row so it stays hidden and
    findable.
    """
    existing = await _find_container_report(db, studio, organization)
    if existing is not None:
        return existing

    from app.services.report_service import ReportService
    from app.schemas.report_schema import ReportCreate

    report_service = ReportService()
    # create_report wires studio-pinned data sources + dashboard layout, then
    # commits. studio_id flows through only when flags.STUDIOS is ON (it is for
    # any org that has AGENT_REPORTS on); flag OFF -> no data sources, but the
    # container is still created so listing/CRUD work.
    schema = await report_service.create_report(
        db,
        ReportCreate(title=_CONTAINER_TITLE, studio_id=studio.id),
        current_user,
        organization,
    )

    report = await db.get(Report, schema.id)
    if report is None:  # defensive — create_report just committed it
        raise HTTPException(status_code=500, detail="Failed to create scheduled-reports container")
    report.report_type = _CONTAINER_TYPE  # durable marker (survives auto-retitle)
    report.status = "archived"  # never surfaced as a normal report
    await db.commit()
    await db.refresh(report)
    return report


async def _get_studio_sp(db: AsyncSession, studio, sp_id: str) -> ScheduledPrompt:
    """Load a scheduled prompt by its own id, scoped to this studio's container.

    Scopes via the prompt's report_id -> report.studio_id + report_type (NOT a
    re-derived container), so the lookup is stable across run-now auto-retitles.
    """
    result = await db.execute(
        select(ScheduledPrompt)
        .join(Report, ScheduledPrompt.report_id == Report.id)
        .where(
            ScheduledPrompt.id == sp_id,
            ScheduledPrompt.deleted_at.is_(None),
            Report.studio_id == studio.id,
            Report.report_type == _CONTAINER_TYPE,
        )
    )
    sp = result.scalar_one_or_none()
    if sp is None:
        raise HTTPException(status_code=404, detail="Scheduled report not found")
    return sp


@router.get("/studios/{studio_id}/scheduled-reports")
async def list_studio_scheduled_reports(
    studio_id: str,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db),
):
    """List this studio's scheduled reports (any role with studio access)."""
    if not flags.AGENT_REPORTS:
        raise HTTPException(status_code=404, detail="Not found")
    role = await resolve_studio_access(db, studio_id, current_user)
    if role is None:
        raise HTTPException(status_code=403, detail="You do not have access to this agent.")
    studio = await _load_studio(db, studio_id, organization)

    # Container may not exist yet (no schedule created) -> empty list, no write.
    container = await _find_container_report(db, studio, organization)
    if container is None:
        return []

    sp_result = await db.execute(
        select(ScheduledPrompt)
        .where(
            ScheduledPrompt.report_id == container.id,
            ScheduledPrompt.deleted_at.is_(None),
        )
        .order_by(ScheduledPrompt.created_at.asc())
    )
    return [_serialize(sp) for sp in sp_result.scalars().all()]


@router.post("/studios/{studio_id}/scheduled-reports")
async def create_studio_scheduled_report(
    studio_id: str,
    data: StudioReportCreate,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db),
):
    """Create a scheduled report bound to this studio (owner/editor only)."""
    if not flags.AGENT_REPORTS:
        raise HTTPException(status_code=404, detail="Not found")
    await _require_report_manager(db, studio_id, current_user)
    studio = await _load_studio(db, studio_id, organization)
    report = await _get_or_create_container_report(db, studio, current_user, organization)

    prompt_json = {
        "content": data.prompt_content,
        "format": _normalize_format(data.format),
        "title": (data.title or "").strip() or None,
    }
    create_payload = ScheduledPromptCreate(
        prompt=prompt_json,
        cron_schedule=data.cron_schedule,
        is_active=data.is_active if data.is_active is not None else True,
        notification_subscribers=data.subscribers,
    )
    # Reuse the existing service (cron validation + APScheduler registration).
    sp = await scheduled_prompt_service.create_scheduled_prompt(
        db, report.id, create_payload, current_user, organization
    )
    return _serialize(sp)


@router.put("/studios/{studio_id}/scheduled-reports/{sp_id}")
async def update_studio_scheduled_report(
    studio_id: str,
    sp_id: str,
    data: StudioReportUpdate,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db),
):
    """Update cron / subscribers / prompt / format / active (owner/editor only)."""
    if not flags.AGENT_REPORTS:
        raise HTTPException(status_code=404, detail="Not found")
    await _require_report_manager(db, studio_id, current_user)
    studio = await _load_studio(db, studio_id, organization)
    sp = await _get_studio_sp(db, studio, sp_id)

    # Merge prompt JSON (content / format / title) when any is supplied.
    new_prompt = None
    if data.prompt_content is not None or data.format is not None or data.title is not None:
        existing = dict(sp.prompt or {})
        if data.prompt_content is not None:
            existing["content"] = data.prompt_content
        if data.format is not None:
            existing["format"] = _normalize_format(data.format)
        if data.title is not None:
            existing["title"] = data.title.strip() or None
        new_prompt = existing

    update_payload = ScheduledPromptUpdate(
        prompt=new_prompt,
        cron_schedule=data.cron_schedule,
        is_active=data.is_active,
        notification_subscribers=data.subscribers,
    )
    updated = await scheduled_prompt_service.update_scheduled_prompt(
        db, sp.id, update_payload, current_user, organization
    )
    return _serialize(updated)


@router.delete("/studios/{studio_id}/scheduled-reports/{sp_id}", status_code=204)
async def delete_studio_scheduled_report(
    studio_id: str,
    sp_id: str,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db),
):
    """Soft-delete + unschedule a scheduled report (owner/editor only)."""
    if not flags.AGENT_REPORTS:
        raise HTTPException(status_code=404, detail="Not found")
    await _require_report_manager(db, studio_id, current_user)
    studio = await _load_studio(db, studio_id, organization)
    sp = await _get_studio_sp(db, studio, sp_id)
    await scheduled_prompt_service.delete_scheduled_prompt(db, sp.id, current_user, organization)


@router.post("/studios/{studio_id}/scheduled-reports/{sp_id}/run-now")
async def run_studio_scheduled_report_now(
    studio_id: str,
    sp_id: str,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db),
):
    """Fire the scheduled run immediately ("Send test now"). Owner/editor only.

    Reuses the exact scheduled-run code path so the test send is identical to a
    real cron fire (runs the prompt + emails subscribers).
    """
    if not flags.AGENT_REPORTS:
        raise HTTPException(status_code=404, detail="Not found")
    await _require_report_manager(db, studio_id, current_user)
    studio = await _load_studio(db, studio_id, organization)
    sp = await _get_studio_sp(db, studio, sp_id)
    await scheduled_prompt_service.scheduled_run_prompt(sp.id)
    return {"status": "triggered", "scheduled_report_id": str(sp.id)}
