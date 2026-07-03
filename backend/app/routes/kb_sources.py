"""Knowledge sources — Notion / Slack sync into the institutional KB (Part E).

Org-scoped, flag-gated (``flags.NOTION_KB``) endpoints that pull Notion pages /
Slack threads into ``KnowledgeDoc`` rows (status ``pending``) so — once approved in
the Knowledge → Review tab — the P4 institutional layer grounds answers with them.

Router carries NO prefix (declared with bare ``/kb-sources/...`` paths); ``main.py``
includes it with ``prefix="/api"``, matching the ``data_source`` router convention.

Flag OFF → every endpoint is a no-op ``{"enabled": False}`` (never touches Notion/
Slack, never hits the DB ingest path). Tokens arrive in the request body only, are
handed straight to the ingest service, and are never logged or persisted in plaintext.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(tags=["kb_sources"])


def _off_payload() -> dict:
    return {"enabled": False}


@router.post("/kb-sources/notion/sync")
async def sync_notion_source(
    token: str = Body(..., embed=True),
    page_ids: Optional[List[str]] = Body(default=None, embed=True),
    auto_approve: bool = Body(default=False, embed=True),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Pull Notion pages into the org's institutional KnowledgeDocs (pending).

    Body: ``{"token": "<notion integration token>", "page_ids": ["…"]?,
    "auto_approve": bool?}``. With no ``page_ids`` the integration's accessible pages
    are discovered. ``auto_approve=true`` flips each synced doc live immediately
    (skips Review); default ``false`` lands them ``pending``. Flag OFF →
    ``{"enabled": False}``. Fail-soft — always returns a summary, never 500s on a
    bad token / unreachable Notion.
    """
    from app.settings.hybrid_flags import flags
    if not flags.NOTION_KB:
        return _off_payload()

    from app.services.knowledge.notion_ingest import sync_notion

    return await sync_notion(
        db,
        organization_id=str(organization.id),
        token=token or "",
        page_ids=page_ids,
        auto_approve=auto_approve,
    )


@router.post("/kb-sources/slack/sync")
async def sync_slack_source(
    token: str = Body(..., embed=True),
    channel_ids: Optional[List[str]] = Body(default=None, embed=True),
    auto_approve: bool = Body(default=False, embed=True),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Pull Slack channel threads into the org's institutional KnowledgeDocs (pending).

    Body: ``{"token": "<slack bot token>", "channel_ids": ["C…"]?,
    "auto_approve": bool?}``. With no ``channel_ids`` the workspace's accessible
    channels are discovered. ``auto_approve=true`` flips each synced doc live
    immediately (skips Review); default ``false`` lands them ``pending``. Flag OFF →
    ``{"enabled": False}``. Fail-soft — always returns a summary.
    """
    from app.settings.hybrid_flags import flags
    if not flags.NOTION_KB:
        return _off_payload()

    from app.services.knowledge.slack_ingest import sync_slack

    return await sync_slack(
        db,
        organization_id=str(organization.id),
        token=token or "",
        channel_ids=channel_ids,
        auto_approve=auto_approve,
    )
