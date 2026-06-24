from sqlalchemy import Column, String, Float, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseSchema


class BrainGraphEdge(BaseSchema):
    """A directed, weighted entity/correlation edge (Phase-8 BRAIN_GRAPH).

    HARD RULE: Apache AGE is dropped (not PG18-ready), so the 2nd-brain graph is
    a plain table + recursive-CTE traversal — NOT an AGE graph. Each row is one
    directed edge ``src_entity --relation--> dst_entity`` with a correlation
    ``weight`` and an optional pgvector ``embedding`` for semantic edge recall.

    Approval-gated like the rest of the learned knowledge layer: a learned /
    proposed edge lands as ``status='draft'`` (or ``'pending'``) and only the
    Phase-8 context builder + traversal surface ``status=='published'`` rows, so
    a non-published edge is automatically invisible to the agent until approved.
    One row per (organization, data_source, src_entity, dst_entity, relation).
    Additive — does not touch dash core.

    NOTE on ``embedding``: declared only on the Postgres ``vector`` column added
    in revision b4rain5graph6. It is intentionally NOT mapped here so the model
    stays SQLite-safe (unit/dev) and import-free of pgvector; edge embeddings are
    read/written via raw SQL in ``app/ai/brain/brain_graph.py`` when present.
    """
    __tablename__ = 'brain_graph_edges'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'data_source_id', 'src_entity', 'dst_entity', 'relation',
            name='uq_brain_graph_edge_org_ds_src_dst_rel',
        ),
    )

    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False, index=True)
    data_source_id = Column(String(36), ForeignKey('data_sources.id'), nullable=True, index=True)

    src_entity = Column(String, nullable=False, index=True)
    dst_entity = Column(String, nullable=False)
    relation = Column(String(100), nullable=False, default='related_to')
    weight = Column(Float, nullable=False, default=0.0)

    # 'published' == live. Anything else (draft/pending/rejected) is invisible
    # to the agent. Mirrors the Instruction/SemanticTable approval convention.
    status = Column(String(50), nullable=False, default='draft')
    # Provenance: 'manual' | 'ai-graph' | 'entity-keymap' | ...
    source = Column(String(50), nullable=False, default='manual')
    structured_data = Column(JSON, nullable=True)

    # Relationships
    organization = relationship("Organization")
    data_source = relationship("DataSource")

    @property
    def is_published(self) -> bool:
        return self.status == "published"

    def __repr__(self):
        return f"<BrainGraphEdge {self.src_entity} -{self.relation}-> {self.dst_entity} ({self.status})>"
