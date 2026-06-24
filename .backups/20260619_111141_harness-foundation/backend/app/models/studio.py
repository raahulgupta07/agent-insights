from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Index

from app.models.base import BaseSchema


class Studio(BaseSchema):
    """Studio (hybrid Studios ST1) — NotebookLM-style shareable agent container.

    Wraps many existing Data Agents (DataSource) as pinned sources, plus a
    persona/system prompt, pinned skills, per-studio brain memory and artifacts,
    and members/roles/sharing. Additive: the `agent`/DataSource subsystem is
    untouched; a Studio merely *references* DataSources via studio_data_sources.

    Sharing: share_scope is 'private' (members only) | 'org' (every org member is
    a viewer) | 'link' (public read-only token; deferred behind ST6). share_token
    is populated only for link scope. All Studios behavior is gated by
    flags.STUDIOS and defaults OFF.
    """

    __tablename__ = "studios"

    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    persona = Column(Text, nullable=True)          # system prompt / persona
    avatar = Column(String, nullable=True)

    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)

    share_scope = Column(String, nullable=False, default="private")  # 'private'|'org'|'link'
    share_token = Column(String, nullable=True, unique=True, index=True)

    config = Column(JSON, nullable=True, default=dict)  # skills, memory scope, model pref

    __table_args__ = (
        Index("ix_studio_org_owner", "organization_id", "owner_user_id"),
    )

    def __repr__(self) -> str:
        return f"<Studio(id={self.id}, name={self.name}, scope={self.share_scope})>"


class StudioDataSource(BaseSchema):
    """Pin an existing Data Agent (DataSource) as a source for a Studio (ST2).

    Does NOT modify the `data_sources` table — it only references it. Retrieval
    inside a Studio chat is scoped to the DataSources pinned here.
    """

    __tablename__ = "studio_data_sources"

    studio_id = Column(String(36), ForeignKey("studios.id"), nullable=False, index=True)
    agent_id = Column(String(36), ForeignKey("data_sources.id"), nullable=False, index=True)

    __table_args__ = (
        Index("ix_studio_ds_studio", "studio_id", "agent_id"),
    )

    def __repr__(self) -> str:
        return f"<StudioDataSource(studio_id={self.studio_id}, agent_id={self.agent_id})>"


class StudioMember(BaseSchema):
    """Explicit per-user membership + role in a Studio (ST1).

    role is one of 'owner'|'editor'|'viewer'. The Studio owner_user_id is the
    implicit owner; this table records additional invited members.
    """

    __tablename__ = "studio_members"

    studio_id = Column(String(36), ForeignKey("studios.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="viewer")  # 'owner'|'editor'|'viewer'

    __table_args__ = (
        Index("ix_studio_member_studio", "studio_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<StudioMember(studio_id={self.studio_id}, user_id={self.user_id}, role={self.role})>"


class StudioSkill(BaseSchema):
    """Pin a Skill to a Studio (ST5). References the existing skills table."""

    __tablename__ = "studio_skills"

    studio_id = Column(String(36), ForeignKey("studios.id"), nullable=False, index=True)
    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=False, index=True)

    __table_args__ = (
        Index("ix_studio_skill_studio", "studio_id", "skill_id"),
    )

    def __repr__(self) -> str:
        return f"<StudioSkill(studio_id={self.studio_id}, skill_id={self.skill_id})>"


class StudioArtifact(BaseSchema):
    """A generated artifact attached to a Studio (ST4).

    kind is one of 'summary'|'faq'|'briefing'|'note' (free-form String). content
    holds the artifact body (Text; may carry JSON-encoded structured payloads).
    """

    __tablename__ = "studio_artifacts"

    studio_id = Column(String(36), ForeignKey("studios.id"), nullable=False, index=True)
    kind = Column(String(50), nullable=False)  # 'summary'|'faq'|'briefing'|'note'
    content = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_studio_artifact_studio", "studio_id", "kind"),
    )

    def __repr__(self) -> str:
        return f"<StudioArtifact(id={self.id}, studio_id={self.studio_id}, kind={self.kind})>"
