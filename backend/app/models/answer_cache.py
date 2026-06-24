from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.models.base import BaseSchema


class AnswerCache(BaseSchema):
    """Tier-1 answer-cache (final-answer reuse).

    Stores a fully-rendered answer (markdown + a small row-count summary) keyed
    by a normalized question hash + data-source scope. On a later, identical
    question the serving funnel can return the cached answer directly instead of
    re-running the whole plan/execute/reflect loop — a Tier-1 cache that sits in
    front of the reasoning-cache (query_cache, which only stores SQL to re-run).

    Unlike query_cache there is no approval gate here: this caches the agent's
    own validated output, optionally with a TTL (expires_at) so stale answers
    age out. NULL expires_at = never expires. Reuse is gated by
    flags.ANSWER_CACHE; everything degrades to a no-op when the flag is off.
    """

    __tablename__ = "answer_cache"

    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)

    # Optional scope: an answer is usually meaningful only against the data
    # source it was computed from. NULL = org-wide.
    data_source_id = Column(String(36), ForeignKey("data_sources.id"), nullable=True, index=True)

    # The user question, normalized (lowercased, whitespace-collapsed, trailing
    # punctuation stripped) and its hash — the dedupe/lookup key.
    question_norm = Column(Text, nullable=False)
    question_hash = Column(String(64), nullable=False, index=True)

    # The rendered answer markdown + a small summary of the result set.
    answer_md = Column(Text, nullable=False)
    row_count = Column(Integer, nullable=False, default=0)

    # The SQL that produced the answer (optional, for provenance / invalidation).
    sql_text = Column(Text, nullable=True)

    # Reuse signal + TTL. expires_at NULL = no expiry.
    hit_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    organization = relationship("Organization")
    data_source = relationship("DataSource")

    __table_args__ = (
        # Fast scoped exact-match lookup by (org, hash).
        Index("ix_answer_cache_lookup", "organization_id", "question_hash"),
    )

    def __repr__(self) -> str:
        return f"<AnswerCache(id={self.id}, hits={self.hit_count})>"
