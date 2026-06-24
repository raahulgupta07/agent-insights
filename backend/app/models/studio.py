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
    # For source='user' (Teach-box authored) packs there is no yaml file on
    # disk, so the full declarative pack dict (id/name/method_text/
    # required_inputs/trigger_hints/output_spec/format) is stored inline here.
    # runtime.resolve_injection reconstructs the pack from this when the
    # registry has no file for pack_id. Null for library ('pack') rows.
    pack_body = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_studio_bound_pack_studio", "studio_id", "status"),
        Index("ix_studio_bound_pack_pack", "studio_id", "pack_id"),
    )

    def __repr__(self) -> str:
        return f"<StudioBoundPack(studio_id={self.studio_id}, pack={self.pack_id}, status={self.status})>"


class PackFireEvent(BaseSchema):
    """Phase 5 — which pack fired on which completion (the winrate signal link).

    Written once per turn at pack-injection time (agent_v2) when the router picks
    a pack. Later, when a user thumbs the completion up/down, the feedback service
    looks this row up by ``completion_id`` and converts the vote into a pass/fail
    on ``PackWinrate``. One row per completion (latest fire wins). Inert unless
    flags.DOMAIN_PACKS — nothing writes or reads it otherwise.
    """

    __tablename__ = "pack_fire_events"

    completion_id = Column(String(36), nullable=False, index=True)
    studio_id = Column(String(36), nullable=False, index=True)
    organization_id = Column(String(36), nullable=True, index=True)
    pack_id = Column(String(120), nullable=False)
    question_cluster = Column(String(160), nullable=True)

    __table_args__ = (
        Index("ix_pack_fire_completion", "completion_id"),
    )

    def __repr__(self) -> str:
        return f"<PackFireEvent(completion={self.completion_id}, pack={self.pack_id})>"


class PackWinrate(BaseSchema):
    """Phase 5 — adaptive win-rate per (studio, pack, question_cluster).

    Aggregated thumbs feedback: ``passes`` (👍) / ``fails`` (👎) and a cached
    ``score`` = passes / (passes + fails). The router reads this to DEMOTE a pack
    that keeps losing on a question pattern (score feeds ``score_candidate`` and a
    proven loser is benched below the select floor). Inert unless DOMAIN_PACKS.
    """

    __tablename__ = "pack_winrates"

    studio_id = Column(String(36), nullable=False, index=True)
    pack_id = Column(String(120), nullable=False, index=True)
    question_cluster = Column(String(160), nullable=False, default="default")
    passes = Column(Integer, nullable=False, default=0)
    fails = Column(Integer, nullable=False, default=0)
    score = Column(Float, nullable=True)  # passes / (passes + fails)

    __table_args__ = (
        Index("ix_pack_winrate_lookup", "studio_id", "pack_id", "question_cluster"),
    )

    def __repr__(self) -> str:
        return f"<PackWinrate(studio={self.studio_id}, pack={self.pack_id}, score={self.score})>"


class OrgPack(BaseSchema):
    """Phase 5 — an org-shared pack (a studio skill promoted to the whole org).

    A user/Teach-authored pack lives inline on one ``StudioBoundPack.pack_body``
    (studio-scoped). Promoting it copies that pack dict here, org-scoped, so every
    studio in the org will autobind it at its next train (``pack_train`` reads
    these alongside the yaml library). The on-disk yaml ``library`` stays the
    immutable shipped set; org packs are the writable, DB-backed extension.
    """

    __tablename__ = "org_packs"

    organization_id = Column(String(36), nullable=False, index=True)
    pack_id = Column(String(120), nullable=False, index=True)
    pack_body = Column(JSON, nullable=False)       # full registry-shaped pack dict
    status = Column(String(20), nullable=False, default="active")  # active|disabled
    source_studio_id = Column(String(36), nullable=True)  # where it was promoted from

    __table_args__ = (
        Index("ix_org_pack_org", "organization_id", "status"),
        Index("ix_org_pack_lookup", "organization_id", "pack_id"),
    )

    def __repr__(self) -> str:
        return f"<OrgPack(org={self.organization_id}, pack={self.pack_id}, status={self.status})>"
