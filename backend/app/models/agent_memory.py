from sqlalchemy import Column, String, Text, Index, DateTime
from app.models.base import BaseSchema


class AgentMemory(BaseSchema):
    """Agent-authored memory (MemGPT-style page-in/out).

    The analyst deliberately stows project state / learnings via the `remember`
    tool and pages them back via `recall` + a context section. Distinct from the
    passive answer/query caches — this captures reasoning, not just answers.

    Scope:
      personal  -> user_id-scoped, status='approved' immediately (own scratchpad).
      project / org -> shared, status='pending' until approved (honors the gate).
    Recall returns only: own approved personal rows OR approved shared rows.
    Vectorless retrieval (PG full-text + token-Jaccard).
    """

    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_agent_memories_org", "organization_id"),
        Index("ix_agent_memories_org_user", "organization_id", "user_id"),
        Index("ix_agent_memories_org_ds", "organization_id", "data_source_id"),
        Index("ix_agent_memories_status", "status"),
    )

    organization_id = Column(String(36), nullable=False)
    user_id = Column(String(36), nullable=True)          # set for scope='personal'
    data_source_id = Column(String(36), nullable=True)   # optional pin

    scope = Column(String(20), nullable=False, default="personal", server_default="personal")
    mem_key = Column(String(200), nullable=True)         # short human label
    text = Column(Text, nullable=False)

    # personal -> 'approved' at write; shared -> 'pending'
    status = Column(String(20), nullable=False, default="approved", server_default="approved")
    source = Column(String(50), nullable=False, default="agent", server_default="agent")

    # --- bi-temporal (HYBRID_BITEMPORAL) -----------------------------------
    # valid_at NULL = since beginning; invalid_at NULL = currently valid.
    valid_at = Column(DateTime, nullable=True)
    invalid_at = Column(DateTime, nullable=True)
    superseded_by = Column(String(36), nullable=True)
