from sqlalchemy import Column, String, Integer, Text, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseSchema


class KnowledgeDoc(BaseSchema):
    """An approval-gated company/business document (Phase-5 DOCS RAG).

    One row per ingested document (upload / paste / connector). The full
    ``body`` is kept for display + re-chunking; retrievable text lives in the
    child ``KnowledgeDocChunk`` rows (chunked at ingest, PG full-text-searched
    by the docs context builder). ``content_hash`` dedupes re-uploads.

    Vectorless by design: retrieval is Postgres full-text search (``to_tsvector``
    / ``plainto_tsquery`` + ``ts_rank``), matching this codebase's no-embedder
    stance (no embedding client exists in the image — see CLAUDE landmines). A
    pgvector upgrade is a later flag-gated follow-up, not required for the gate
    (a term-definition question resolving from an approved doc).

    Approval-gated like the rest of the learned knowledge layer: an ingested
    doc lands ``status='pending'`` and ONLY ``status=='approved'`` docs (and
    their chunks) surface to the agent's ``### Company definitions`` context, so
    an un-approved doc is automatically invisible until a human approves it
    (mirrors the TableEdge / BrainGraphEdge / SemanticTable convention).
    Additive — does not touch dash core.
    """
    __tablename__ = 'knowledge_docs'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'data_source_id', 'content_hash',
            name='uq_knowledge_doc_org_ds_hash',
        ),
    )

    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False, index=True)
    data_source_id = Column(String(36), ForeignKey('data_sources.id'), nullable=True, index=True)

    title = Column(String, nullable=False, default='')
    # 'upload' | 'paste' | 'notion' | 'slack' | 'gdrive' | 'url'
    source = Column(String(20), nullable=False, default='upload')
    body = Column(Text, nullable=False, default='')
    url = Column(String, nullable=True)
    content_hash = Column(String(64), nullable=False, index=True)

    # 'approved' == live. Anything else (pending/rejected) is invisible to the
    # agent. Ingested docs land 'pending'. Mirrors the approval convention.
    status = Column(String(20), nullable=False, default='pending', index=True)
    structured_data = Column(JSON, nullable=True)

    organization = relationship("Organization")
    data_source = relationship("DataSource")
    chunks = relationship(
        "KnowledgeDocChunk",
        back_populates="doc",
        cascade="all, delete-orphan",
    )

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    def __repr__(self):
        return f"<KnowledgeDoc {self.title!r} ({self.status})>"


class KnowledgeDocChunk(BaseSchema):
    """One retrievable chunk of a ``KnowledgeDoc``.

    The full-text-search target. A GIN functional index on
    ``to_tsvector('english', text)`` is created in the migration; the docs
    context builder ranks chunks with ``ts_rank`` against the question and only
    surfaces chunks whose PARENT doc is ``status='approved'``.
    """
    __tablename__ = 'knowledge_doc_chunks'

    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False, index=True)
    doc_id = Column(String(36), ForeignKey('knowledge_docs.id'), nullable=False, index=True)

    chunk_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False, default='')

    doc = relationship("KnowledgeDoc", back_populates="chunks")

    def __repr__(self):
        return f"<KnowledgeDocChunk doc={self.doc_id} #{self.chunk_index}>"
