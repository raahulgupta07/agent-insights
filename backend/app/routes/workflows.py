"""HTTP surface for the deterministic WORKFLOW RUNNER (#5).

POST /api/workflows/{name}/run : run a named deterministic batch workflow
(fan a work-list through a stage worker with a per-item verifier gate) and
return its summary + per-item log. Flag-gated (HYBRID_WORKFLOWS), org-scoped,
approval-safe (the underlying jobs only PROPOSE pending knowledge).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.data_source import DataSource
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Static per-job presentation metadata for the LIST endpoint. Keyed by the
# registry name in `jobs.WORKFLOWS`. Unknown names fall back gracefully
# (see _workflow_meta) so the list never breaks when a job is added.
WORKFLOW_METADATA: dict[str, dict] = {
    "train_connector_tables": {
        "description": "Profile and train all connector tables",
        "max_concurrency": 1,
    },
}

# Lightweight in-process status store. Runs are synchronous/ephemeral (there is
# NO persisted run table), so this is the only record of the last run per
# workflow name. Survives only for the process lifetime; empty is fine.
_LAST_RUNS: dict[str, dict] = {}


def _humanize(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").title()


def _workflow_meta(name: str) -> dict:
    meta = WORKFLOW_METADATA.get(name, {})
    return {
        "name": name,
        "label": _humanize(name),
        "description": meta.get("description", ""),
        "max_concurrency": meta.get("max_concurrency"),
    }


class NotifySubscriber(BaseModel):
    # type='email' → use `address`; type='user' → resolve `id` → users.email
    type: str = "email"
    address: Optional[str] = None
    id: Optional[str] = None


class NotifyConfig(BaseModel):
    """OPT-IN delivery hook. When present (and HYBRID_RICH_REPORT_EMAIL is on)
    the run summary is emailed via the universal report-delivery layer. Absent =
    behaviour is exactly as before (no email, no extra work)."""
    subscribers: List[NotifySubscriber] = []
    studio_id: Optional[str] = None  # routes via the agent's own SMTP identity
    title: Optional[str] = None      # email subject/title override


class RunWorkflowRequest(BaseModel):
    data_source_id: str
    max_tables: int = 25
    use_llm_judge: bool = False
    # OPTIONAL — omit for unchanged behaviour.
    notify: Optional[NotifyConfig] = None


async def _resolve_subscriber_emails(
    subscribers: List[NotifySubscriber],
    *,
    db: AsyncSession,
    organization: Organization,
) -> List[str]:
    """Resolve subscriber descriptors → a de-duped list of email addresses.

    ``email`` subscribers contribute their address directly; ``user``
    subscribers are looked up in ``users`` (org-scoped via Membership) →
    ``User.email``. Fail-soft: a bad/unknown subscriber is skipped, never
    raises into the send path."""
    emails: list[str] = []
    user_ids: list[str] = []
    for sub in subscribers:
        if (sub.type or "email").lower() == "email":
            if sub.address:
                emails.append(sub.address.strip())
        elif (sub.type or "").lower() == "user" and sub.id:
            user_ids.append(sub.id)

    if user_ids:
        try:
            from app.models.membership import Membership

            rows = (
                await db.execute(
                    select(User.email)
                    .join(Membership, Membership.user_id == User.id)
                    .where(
                        User.id.in_(user_ids),
                        Membership.organization_id == organization.id,
                    )
                )
            ).scalars().all()
            emails.extend([e for e in rows if e])
        except Exception:  # noqa: BLE001 — never break the run on a lookup fail
            logger.warning("workflow notify: user-id email lookup failed", exc_info=True)

    # de-dupe, preserve order, drop empties
    seen: set[str] = set()
    out: list[str] = []
    for e in emails:
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out


async def _maybe_notify(
    summary: dict,
    notify: NotifyConfig,
    *,
    name: str,
    db: AsyncSession,
    organization: Organization,
) -> bool:
    """Email the workflow run summary via the universal report-delivery layer.

    Flag-gated (HYBRID_RICH_REPORT_EMAIL) and fully fail-soft: ANY failure here
    is logged and swallowed so the workflow run itself is never affected. Returns
    True only if a delivery was attempted and reported success."""
    from app.settings.hybrid_flags import flags

    if not flags.RICH_REPORT_EMAIL:
        return False

    try:
        recipient_emails = await _resolve_subscriber_emails(
            notify.subscribers, db=db, organization=organization
        )
        if not recipient_emails:
            logger.info("workflow notify: no recipient emails resolved, skipping")
            return False

        from app.services.report_delivery.assembler import deliver
        from app.services.report_delivery.contract import DeliveryContext

        label = (summary or {}).get("label") if isinstance(summary, dict) else None
        ctx = DeliveryContext(
            # No persisted report for a workflow run → synthetic stable id. The
            # renderer's narrative/extract helpers find nothing for it (fine) and
            # build the body from options['workflow_run'].
            report_id=f"workflow:{name}",
            organization_id=organization.id,
            studio_id=notify.studio_id,
            title=notify.title or label or _humanize(name),
            options={
                "source": "workflow",
                "workflow_run": summary,
                "format": "workflow",
            },
        )
        return await deliver(ctx, recipient_emails, db=db)
    except Exception:  # noqa: BLE001 — email must NEVER fail the workflow run
        logger.warning("workflow notify: delivery failed (run unaffected)", exc_info=True)
        return False


@router.get("")
async def list_workflows(
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    """List available deterministic workflows. Returns [] when the flag is off
    so the page can render an empty/disabled state (run_workflow 403s; a LIST
    is better empty)."""
    from app.settings.hybrid_flags import flags

    if not flags.WORKFLOWS:
        return []

    from app.ai.workflows import jobs

    return [_workflow_meta(name) for name in jobs.WORKFLOWS]


@router.get("/{name}/status")
async def get_workflow_status(
    name: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    """Last-run status for a workflow (in-process, ephemeral). Idle if never
    run this process lifetime."""
    return _LAST_RUNS.get(name) or {"status": "idle", "name": name}


@router.post("/{name}/run")
async def run_workflow(
    name: str,
    body: RunWorkflowRequest,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    from app.settings.hybrid_flags import flags

    if not flags.WORKFLOWS:
        raise HTTPException(
            status_code=403, detail="workflows are disabled (HYBRID_WORKFLOWS off)"
        )

    from app.ai.workflows import jobs

    job = jobs.WORKFLOWS.get(name)
    if job is None:
        raise HTTPException(status_code=404, detail=f"workflow '{name}' not found")

    ds = (
        await db.execute(
            select(DataSource).where(
                DataSource.id == body.data_source_id,
                DataSource.organization_id == organization.id,
            )
        )
    ).scalars().first()
    if ds is None:
        raise HTTPException(status_code=404, detail="data_source not found")

    try:
        summary = await job(
            db=db,
            organization=organization,
            user=user,
            data_source=ds,
            max_tables=body.max_tables,
            use_llm_judge=body.use_llm_judge,
        )
    except Exception as exc:  # noqa: BLE001 - record then re-raise unchanged
        _LAST_RUNS[name] = {
            "status": "error",
            "name": name,
            "error": str(exc),
            "finished_at": datetime.utcnow().isoformat(),
        }
        raise

    _LAST_RUNS[name] = {
        "status": "done",
        "name": name,
        "summary": summary,
        "finished_at": datetime.utcnow().isoformat(),
    }

    # OPT-IN delivery hook: email the run summary via the universal report-delivery
    # layer. Only fires when `notify` is supplied AND the flag is on; fully
    # fail-soft (never affects the run). Default path = unchanged.
    if body.notify is not None:
        notified = await _maybe_notify(
            summary, body.notify, name=name, db=db, organization=organization
        )
        if isinstance(summary, dict):
            summary = {**summary, "notified": notified}

    return summary
