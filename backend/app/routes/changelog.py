"""Changelog ("What's new") data API — read-only, fail-soft.

Surfaces the hybrid feature changelog (parsed from CHANGELOG_HYBRID.md at the
repo root) plus a per-user "last seen" so the UI can render an unseen badge.

All handlers are fail-soft: any error degrades to a safe empty payload and a
warning log — never a 500. Additive — the only core file touched is the router
registration in main.py.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.models.user import User
from app.models.organization import Organization
from app.services.changelog import (
    load_changelog,
    current_version,
    entries_after,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/changelog", tags=["changelog"])


@router.get("")
async def get_changelog(
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
) -> dict[str, Any]:
    """Full changelog + current version. Read-only, fail-soft."""
    try:
        return {"current": current_version(), "entries": load_changelog()}
    except Exception as e:  # noqa: BLE001
        logger.warning("changelog.get_changelog failed: %s", e)
        return {"current": "0.0.0", "entries": []}


@router.get("/unseen")
async def get_unseen(
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
) -> dict[str, Any]:
    """Count + latest of entries newer than the user's last_seen_changelog."""
    try:
        entries = load_changelog()
        last_seen = getattr(current_user, "last_seen_changelog", None)
        unseen = entries_after(entries, last_seen)
        return {
            "count": len(unseen),
            "latest": entries[0] if entries else None,
            "current": current_version(),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("changelog.get_unseen failed: %s", e)
        return {"count": 0, "latest": None, "current": "0.0.0"}


@router.post("/seen")
async def mark_seen(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict[str, Any]:
    """Mark the current version as seen for the current user."""
    ver = "0.0.0"
    try:
        ver = current_version()
        # Reload the user by PK in THIS session to avoid detached-instance
        # issues (the dependency-injected user may be from another session).
        res = await db.execute(select(User).where(User.id == current_user.id))
        user = res.scalar_one_or_none()
        if user is None:
            return {"ok": False, "seen": ver}
        user.last_seen_changelog = ver
        await db.commit()
        return {"ok": True, "seen": ver}
    except Exception as e:  # noqa: BLE001
        logger.warning("changelog.mark_seen failed: %s", e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "seen": ver}
