"""In-app notification INBOX API (bell + dropdown).

Every handler is org- AND user-scoped via the fork's auth dependencies. Distinct
from the outbound-email `notification_service` — this serves the in-app inbox only.
The router is mounted unconditionally; the FE hides the bell behind
HYBRID_NOTIFICATIONS_INBOX.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.models.user import User
from app.models.organization import Organization
from app.services.notification_inbox_service import notification_inbox_service
from app.schemas.notification_inbox_schema import (
    NotificationItem,
    NotificationList,
    UnreadCount,
)

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    rows = await notification_inbox_service.list_for_user(
        db, organization.id, current_user.id, limit=limit, offset=offset
    )
    unread = await notification_inbox_service.unread_count(
        db, organization.id, current_user.id
    )
    return NotificationList(
        items=[NotificationItem.from_orm(r) for r in rows],
        unread=unread,
    )


@router.get("/notifications/count", response_model=UnreadCount)
async def count_notifications(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    unread = await notification_inbox_service.unread_count(
        db, organization.id, current_user.id
    )
    return UnreadCount(unread=unread)


@router.post("/notifications/read-all")
async def read_all_notifications(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    marked = await notification_inbox_service.mark_all_read(
        db, organization.id, current_user.id
    )
    return {"ok": True, "marked": marked}


@router.post("/notifications/{notification_id}/read")
async def read_notification(
    notification_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    row = await notification_inbox_service.mark_read(
        db, organization.id, current_user.id, notification_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/notifications/{notification_id}/dismiss")
async def dismiss_notification(
    notification_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    row = await notification_inbox_service.dismiss(
        db, organization.id, current_user.id, notification_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}
