from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.models.base import BaseSchema


class QueryCache(BaseSchema):
    """Reasoning-cache (Phase 4 read / Phase 5 write).

    Stores proven read-only SELECTs the agent has run successfully, keyed by a
    normalized question hash + data-source scope. On a later, similar question
    the planner is shown these as "PROVEN QUERIES" context (Phase 4 BRAIN_READ),
    and a downstream serve path may re-run the stored SQL LIVE for fresh numbers
    (no hardcoded results — the SQL is re-executed).

    Everything learned lands in status='pending' and goes live only after the
    dash approval gate promotes it to 'active' — same gate as Instructions, no
    new gate. Capture is gated by flags.QUERY_CACHE; injection by flags.BRAIN_READ.
    """

    __tablename__ = "query_cache"

    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)

    # Optional scope: a proven query is usually meaningful only against the
    # data source whose schema it targets. NULL = org-wide.
    data_source_id = Column(String(36), ForeignKey("data_sources.id"), nullable=True, index=True)

    # The user question, normalized (lowercased, whitespace-collapsed, trailing
    # punctuation stripped) and its hash — the dedupe/lookup key.
    question_norm = Column(Text, nullable=False)
    question_hash = Column(String(64), nullable=False, index=True)

    # The proven read-only SQL. Re-run live on serve; never store result rows.
    sql_text = Column(Text, nullable=False)

    # Lifecycle: pending -> active (approval gate) ; rejected drops it.
    status = Column(String(20), nullable=False, default="pending", index=True)

    # Provenance + signal for the curator/approval surface.
    source = Column(String(20), nullable=False, default="chat")  # chat | curator | manual
    hit_count = Column(Integer, nullable=False, default=0)
    thumbs_down = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)

    organization = relationship("Organization")
    data_source = relationship("DataSource")

    __table_args__ = (
        # Fast scoped lookup by (org, data_source, hash, status).
        Index("ix_query_cache_lookup", "organization_id", "data_source_id", "question_hash", "status"),
    )

    def __repr__(self) -> str:
        return f"<QueryCache(id={self.id}, status={self.status}, hits={self.hit_count})>"
