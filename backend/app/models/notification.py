from sqlalchemy import Column, String, Text, JSON, DateTime, ForeignKey, Boolean, Index

from app.models.base import BaseSchema


# ── Sources (where the notification was produced) ───────────────────────────────
SOURCE_REVIEW = "review"
SOURCE_SHARE = "share"
SOURCE_REPORT = "report"
SOURCE_SCHEDULE = "schedule"
SOURCE_SYSTEM = "system"

# ── Severity (drives sort + accent) ─────────────────────────────────────────────
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"


class Notification(BaseSchema):
    """One in-app inbox notification (the per-recipient delivery row).

    IMPORTANT: this is the fork's greenfield *inbox* model (a bell in the nav with
    read/dismiss state). It is UNRELATED to the outbound-email sender in
    `services/notification_service.py` / `schemas/notification_schema.py` — those
    send SMTP mail and are left untouched.

    A ``user_id`` of NULL means the notification is org-wide (delivered to every
    member of the org); a concrete ``user_id`` targets a single recipient who owns
    that row's read/dismiss state.
    """

    __tablename__ = "notifications"

    organization_id = Column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # NULL = org-wide (all members see it); set = a single recipient.
    user_id = Column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    # Who/what caused it (the sharer, or NULL for system/agent producers).
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    source = Column(String, nullable=False, default=SOURCE_SYSTEM, index=True)
    type = Column(String, nullable=False, default="generic")
    severity = Column(String, nullable=False, default=SEVERITY_INFO)

    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    # Frontend deep-link target, e.g. "/reports/<id>".
    link = Column(String, nullable=True)
    # Free-form structured payload for future producers.
    data = Column(JSON, nullable=True, default=dict)

    # Per-recipient triage state.
    is_read = Column(Boolean, nullable=False, default=False)
    read_at = Column(DateTime, nullable=True)
    is_dismissed = Column(Boolean, nullable=False, default=False)
    dismissed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_notifications_org_user_read", "organization_id", "user_id", "is_read"),
        Index("ix_notifications_created_at", "created_at"),
    )
