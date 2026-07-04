"""In-app notification INBOX service (bell + dropdown).

Distinct from `services/notification_service.py` (outbound SMTP email) — this owns
the per-recipient inbox rows and their read/dismiss state.

STRICT scoping invariant (the fork had a real cross-org console leak):
every query filters by ``organization_id`` AND
``(user_id == caller OR user_id IS NULL)`` so a caller only ever sees their own
notifications plus org-wide ones, and never another org's or another user's.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, SEVERITY_INFO, SOURCE_SYSTEM


def _scope(organization_id: str, user_id: str):
    """The shared org+user scoping predicate (see module docstring)."""
    return and_(
        Notification.organization_id == organization_id,
        or_(Notification.user_id == user_id, Notification.user_id.is_(None)),
        Notification.deleted_at.is_(None),
        Notification.is_dismissed.is_(False),
    )


class NotificationInboxService:

    async def list_for_user(
        self,
        db: AsyncSession,
        organization_id: str,
        user_id: str,
        *,
        limit: int = 30,
        offset: int = 0,
    ) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(_scope(organization_id, user_id))
            .order_by(Notification.created_at.desc())
            .limit(max(1, min(limit, 100)))
            .offset(max(0, offset))
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def unread_count(
        self, db: AsyncSession, organization_id: str, user_id: str
    ) -> int:
        stmt = select(func.count()).select_from(Notification).where(
            and_(_scope(organization_id, user_id), Notification.is_read.is_(False))
        )
        result = await db.execute(stmt)
        return int(result.scalar() or 0)

    async def _get_owned(
        self, db: AsyncSession, organization_id: str, user_id: str, notification_id: str
    ) -> Optional[Notification]:
        """Fetch a single row only if it belongs to the caller's org+user scope.

        Returns None (→ 404) rather than leaking the existence of out-of-scope rows.
        """
        stmt = select(Notification).where(
            and_(_scope(organization_id, user_id), Notification.id == notification_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_read(
        self, db: AsyncSession, organization_id: str, user_id: str, notification_id: str
    ) -> Optional[Notification]:
        row = await self._get_owned(db, organization_id, user_id, notification_id)
        if row is None:
            return None
        if not row.is_read:
            row.is_read = True
            row.read_at = datetime.utcnow()
            await db.commit()
        return row

    async def mark_all_read(
        self, db: AsyncSession, organization_id: str, user_id: str
    ) -> int:
        stmt = (
            update(Notification)
            .where(and_(_scope(organization_id, user_id), Notification.is_read.is_(False)))
            .values(is_read=True, read_at=datetime.utcnow())
        )
        result = await db.execute(stmt)
        await db.commit()
        return int(result.rowcount or 0)

    async def dismiss(
        self, db: AsyncSession, organization_id: str, user_id: str, notification_id: str
    ) -> Optional[Notification]:
        row = await self._get_owned(db, organization_id, user_id, notification_id)
        if row is None:
            return None
        row.is_dismissed = True
        row.dismissed_at = datetime.utcnow()
        if not row.is_read:
            row.is_read = True
            row.read_at = datetime.utcnow()
        await db.commit()
        return row

    async def create_notification(
        self,
        db: AsyncSession,
        *,
        organization_id: str,
        title: str,
        user_id: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        source: str = SOURCE_SYSTEM,
        type: str = "generic",
        severity: str = SEVERITY_INFO,
        body: Optional[str] = None,
        link: Optional[str] = None,
        data: Optional[dict] = None,
    ) -> Notification:
        """Helper for future producers. NOTE: no producers are wired this round —
        the inbox may legitimately be empty. ``user_id=None`` = org-wide.
        """
        row = Notification(
            organization_id=organization_id,
            user_id=user_id,
            actor_user_id=actor_user_id,
            source=source,
            type=type,
            severity=severity,
            title=title,
            body=body,
            link=link,
            data=data or {},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


notification_inbox_service = NotificationInboxService()
