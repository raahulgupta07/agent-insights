from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.models.base import BaseSchema


class CodeCache(BaseSchema):
    """Code-memory bank (Kepler Phase 2) — the python analogue of QueryCache.

    Stores the proven ``generate_df(ds_clients, excel_files)`` python the agent
    wrote for a successful answer, keyed by a normalized-question hash + data
    source scope. On a later similar question the Coder is shown the closest
    snippet(s) as PROVEN APPROACHES context so it reuses the working join/dedup/
    filter logic instead of re-deriving it ("code matters more than schemas").

    Unlike QueryCache, this is NEVER executed — it is injected as reference text
    only, so captured rows land status='active' immediately (the code already
    succeeded). A future review surface can downgrade. Capture + injection are
    both gated by flags.CODE_BANK; everything degrades to a no-op when off.

    This mirrors app/models/query_cache.py intentionally (clone, not new design).
    """

    __tablename__ = "code_cache"

    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    # NULL = org-wide; usually scoped to the data source the code targeted.
    data_source_id = Column(String(36), ForeignKey("data_sources.id"), nullable=True, index=True)

    # The user question, normalized + hashed — the dedupe/lookup key.
    question_norm = Column(Text, nullable=False)
    question_hash = Column(String(64), nullable=False, index=True)

    # The proven generate_df python. Injected as context; never executed here.
    code = Column(Text, nullable=False)

    # Lifecycle: active (reusable) ; a future review surface may set 'archived'.
    status = Column(String(20), nullable=False, default="active", index=True)

    source = Column(String(20), nullable=False, default="chat")  # chat | manual
    hit_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)

    organization = relationship("Organization")
    data_source = relationship("DataSource")

    __table_args__ = (
        Index("ix_code_cache_lookup", "organization_id", "data_source_id", "question_hash", "status"),
    )

    def __repr__(self) -> str:
        return f"<CodeCache(id={self.id}, status={self.status}, hits={self.hit_count})>"
