from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import BaseSchema


class ApiKey(BaseSchema):
    __tablename__ = "api_keys"

    # NULL for service-account keys (they are not backed by a human user row);
    # set for keys minted by a real user (MCP / sync).
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)  # e.g., "MCP Integration", "CI Pipeline"
    key_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hash
    key_prefix = Column(String(12), nullable=False)  # First 12 chars for identification (e.g., "bow_abc123...")
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    # Set when this key belongs to a service account (its owning account).
    service_account_id = Column(String(36), ForeignKey("service_accounts.id"), nullable=True, index=True)
    # Set when the key is revoked; a revoked key must never authenticate.
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="api_keys")
    organization = relationship("Organization")
    service_account = relationship(
        "ServiceAccount",
        back_populates="keys",
        foreign_keys=[service_account_id],
    )
