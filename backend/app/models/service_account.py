from sqlalchemy import Column, String, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import BaseSchema


class ServiceAccount(BaseSchema):
    """A machine / service principal an org admin creates for headless,
    programmatic access.

    A service account is org-owned metadata only — it holds one or more API
    keys (rows in ``api_keys`` with ``service_account_id`` set and ``user_id``
    NULL) that are used for headless access. It is NOT backed by a human
    ``users`` row, so it consumes no seat and never appears in member lists.

    Org binding lives here (``organization_id``); every service-account route
    is org-scoped and admin-gated.
    """

    __tablename__ = "service_accounts"

    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # The human admin who created the account (NULL if they were later deleted).
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    # When False the account is disabled — no new keys should be issued and its
    # keys should be treated as revoked at auth time.
    is_active = Column(Boolean, nullable=False, default=True)

    organization = relationship("Organization")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    keys = relationship(
        "ApiKey",
        back_populates="service_account",
        foreign_keys="ApiKey.service_account_id",
    )
