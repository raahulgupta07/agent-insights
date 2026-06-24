from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, Index

from app.models.base import BaseSchema


class Skill(BaseSchema):
    """Self-service Skill (Phase 6).

    A Claude-style SKILL.md capability with progressive disclosure: the L1
    catalog shows name + description; the full SKILL.md body (skill_md, L2) is
    loaded on demand. Skills are scoped personal / org / global and become
    visible only when status='active'. Capture/authoring and visibility are
    gated by flags.SKILLS.
    """

    __tablename__ = "skills"

    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=False)
    scope = Column(String, nullable=False, default="personal", index=True)  # 'personal'|'org'|'global'
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True, index=True)
    skill_md = Column(Text, nullable=False)  # full SKILL.md body (L2)
    category = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="draft")  # draft|active|archived (active = visible)
    hit_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)

    # Phase S1.1 — Claude-style SKILL.md frontmatter fields (all nullable/safe-default)
    allowed_tools = Column(Text, nullable=True)        # JSON-encoded list of tool names
    disallowed_tools = Column(Text, nullable=True)     # JSON-encoded list of tool names
    disable_model_invocation = Column(Boolean, nullable=False, default=False)
    user_invocable = Column(Boolean, nullable=False, default=True)
    skill_metadata = Column(Text, nullable=True)       # JSON dict
    license = Column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_skill_visibility", "organization_id", "scope", "status"),
        Index("ix_skill_owner", "owner_user_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Skill(id={self.id}, name={self.name}, scope={self.scope}, status={self.status})>"
