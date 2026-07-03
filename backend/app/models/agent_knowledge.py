from sqlalchemy import Column, String, Integer, Text, JSON, Index, UniqueConstraint
from app.models.base import BaseSchema


class AgentKnowledge(BaseSchema):
    """Singularized, reusable agent knowledge — the cross-user learning store.

    Distinct from ``AgentMemory`` (the MemGPT remember/recall scratchpad): this
    is AUTO-captured, DEDUPED (one canonical row per fact), SANITIZED (no data
    values — see services/knowledge/sanitize), and SCOPED by a resolver so a
    learning reaches only agents/users who legitimately share that scope.

    Two tiers, one table:
      SHARED  -> scope_kind in {model, schema, file}; keyed by scope_key
                 (Power BI semantic-model GUID / DB schema signature / file
                 signature). Identical scope_key ONLY for users with the same
                 access, so sharing is safe by construction. Compounds across
                 users; access = intersection with the viewer's own scopes.
      PRIVATE -> scope_kind='user'; scope_key = user_id. Never crosses users
                 (personal agents / own scratchpad-grade learnings).

    Singularize key = (organization_id, scope_kind, scope_key, kind,
    source_hash). Re-learning the same fact bumps ``verified_count`` instead of
    inserting a duplicate; a fact is promoted to trusted at verified_count >= 2
    (or via an explicit golden). No FK constraints by design (enrichment table,
    same convention as column_profiles / ingest_batches — avoids delete-cascade
    coupling).
    """

    __tablename__ = "agent_knowledge"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "scope_kind", "scope_key", "kind", "source_hash",
            name="uq_agent_knowledge_singular",
        ),
        Index("ix_agent_knowledge_org", "organization_id"),
        Index("ix_agent_knowledge_scope", "organization_id", "scope_kind", "scope_key"),
        Index("ix_agent_knowledge_status", "status"),
        Index("ix_agent_knowledge_user", "organization_id", "created_by_user_id"),
    )

    organization_id = Column(String(36), nullable=False)

    # --- scope (the isolation key) ----------------------------------------
    # scope_kind: 'model' (PBI dataset_id) | 'schema' (DB schema-sig) |
    #             'file' (file-sig) | 'user' (private, = user_id)
    scope_kind = Column(String(20), nullable=False, default="model", server_default="model")
    scope_key = Column(String(200), nullable=False)

    # --- the learning ------------------------------------------------------
    # kind: 'meaning' | 'join' | 'dax_template' | 'query_template' | 'mistake' | 'howto'
    kind = Column(String(20), nullable=False)
    title = Column(String(300), nullable=True)          # short human label
    content_json = Column(JSON, nullable=True)          # SANITIZED payload
    text = Column(Text, nullable=True)                  # optional flat form for FTS/injection

    # dedupe / singularize
    source_hash = Column(String(64), nullable=False)
    verified_count = Column(Integer, nullable=False, default=1, server_default="1")

    # provenance
    created_by_user_id = Column(String(36), nullable=True)  # who first taught (owner for private tier)
    data_source_id = Column(String(36), nullable=True)      # optional pin

    # 'active' (trusted, injectable) | 'pending' (seen once, not yet promoted) | 'rejected'
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
