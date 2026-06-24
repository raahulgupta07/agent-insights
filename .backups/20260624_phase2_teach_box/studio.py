from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey, JSON, Index

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

    # Studio Context Harness (ST7): records which auto-born steps have run
    # (avatar/voice/summary/suggestedQs/instructions/examples). Filled by the
    # background bootstrap pipeline; flag-gated by HYBRID_STUDIOS.
    bootstrap_state = Column(JSON, nullable=True, default=dict)

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


class StudioInstruction(BaseSchema):
    """A per-studio instruction / rule (ST7 + ST8).

    Auto-born from schema (source='auto') or hand-written (source='manual').
    Rules are ALWAYS born `pending` and only reach the agent once a human flips
    them to `active` via the existing review gate. instruction_id optionally
    links to a dash `instructions` row when the rule is promoted into dash's
    native Instruction/approval subsystem.
    """

    __tablename__ = "studio_instructions"

    studio_id = Column(String(36), ForeignKey("studios.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    source = Column(String, nullable=False, default="auto")    # 'auto'|'manual'
    status = Column(String, nullable=False, default="pending")  # 'pending'|'active'
    score = Column(Float, nullable=True)
    instruction_id = Column(String(36), ForeignKey("instructions.id"), nullable=True, index=True)

    __table_args__ = (
        Index("ix_studio_instruction_studio", "studio_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<StudioInstruction(id={self.id}, studio_id={self.studio_id}, status={self.status})>"


class StudioExample(BaseSchema):
    """A per-studio golden few-shot example (ST7 + ST8).

    Mined from the query bank or generated Q->answer (source='auto') or
    hand-written (source='manual'). ALWAYS born `pending` -> reaches the agent
    only after a human flips it to `active`. `uses` tracks how often the example
    has been served so the learning loop can rank/prune.
    """

    __tablename__ = "studio_examples"

    studio_id = Column(String(36), ForeignKey("studios.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    sql = Column(Text, nullable=True)
    source = Column(String, nullable=False, default="auto")    # 'auto'|'manual'
    status = Column(String, nullable=False, default="pending")  # 'pending'|'active'
    uses = Column(Integer, nullable=False, default=0)
    score = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_studio_example_studio", "studio_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<StudioExample(id={self.id}, studio_id={self.studio_id}, status={self.status})>"


class StudioBoundPack(BaseSchema):
    """A Domain Pack bound to a Studio (the lightweight "skills" engine).

    A *pack* is a declarative method file in ``app/ai/packs/library``. When its
    required inputs match a studio's real columns the binder writes a row here:
    the per-agent VARIABLE binding (logical input -> column name) for that
    pack's INVARIANT method. The router later candidate-gates on the ACTIVE
    rows of this table, so a pack the agent's data can't support is never even
    a candidate (that is the fix for native Skills' wrong-skill picks).

    Lifecycle: born `pending` (review gate) -> human approves -> `active`
    (router can pick it) ; binder finds a required input missing -> `dormant`
    (recorded so the UI can say "needs a Budget column") ; rejected -> `rejected`.

    All of this is gated by flags.DOMAIN_PACKS (default OFF). source is 'pack'
    for the shipped library or 'user' for a Teach-box / Skill-Builder authored
    pack (Phase 2+).
    """

    __tablename__ = "studio_bound_packs"

    studio_id = Column(String(36), ForeignKey("studios.id"), nullable=False, index=True)
    pack_id = Column(String(120), nullable=False, index=True)   # registry slug
    binding_map = Column(JSON, nullable=True, default=dict)     # {input_key: column_name}
    output_spec = Column(JSON, nullable=True, default=dict)     # snapshot of the pack output_spec
    eval_goldens = Column(JSON, nullable=True, default=list)    # snapshotted expected results
    status = Column(String(20), nullable=False, default="pending")  # pending|active|dormant|rejected
    source = Column(String(20), nullable=False, default="pack")     # 'pack'|'user'
    conf = Column(Float, nullable=True)                        # overall bind confidence 0..1
    missing = Column(JSON, nullable=True, default=list)        # unmatched required inputs (if dormant)

    __table_args__ = (
        Index("ix_studio_bound_pack_studio", "studio_id", "status"),
        Index("ix_studio_bound_pack_pack", "studio_id", "pack_id"),
    )

    def __repr__(self) -> str:
        return f"<StudioBoundPack(studio_id={self.studio_id}, pack={self.pack_id}, status={self.status})>"
