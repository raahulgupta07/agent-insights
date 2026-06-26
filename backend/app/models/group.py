from sqlalchemy import Column, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.models.base import BaseSchema


class Group(BaseSchema):
    __tablename__ = 'groups'
    __table_args__ = (
        UniqueConstraint('organization_id', 'name', name='uq_groups_org_name'),
    )

    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    external_id = Column(String, nullable=True)       # AD/Okta/SCIM group ID
    external_provider = Column(String, nullable=True)  # "azure_ad", "okta", "scim"
    # Hybrid user-owned groups (HYBRID_USER_GROUPS, default OFF). NULL = an
    # org / admin / LDAP group (unchanged upstream behavior). Set = a personal
    # group owned by one user, used as a reusable share target. Indexed for the
    # per-user list query.
    owner_user_id = Column(String(36), ForeignKey('users.id'), nullable=True, index=True)

    organization = relationship("Organization", back_populates="groups")
    memberships = relationship("GroupMembership", back_populates="group", cascade="all, delete-orphan")
