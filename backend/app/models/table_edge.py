from sqlalchemy import Column, String, Float, Integer, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseSchema


class TableEdge(BaseSchema):
    """An approval-gated learned join / lineage edge (Phase-6 JOIN GRAPH).

    Each row is one join relationship between two tables/columns
    ``left_table.left_col <--> right_table.right_col`` with a ``join_count``
    (how often the pair co-occurred in proven SQL) and a ``confidence`` score.
    ``source`` records provenance: ``'inferred'`` (mined from observed joins)
    or ``'declared'`` (human-declared FK / explicit relationship).

    Approval-gated like the rest of the learned knowledge layer: a mined edge
    lands as ``status='pending'`` and ONLY ``status=='approved'`` rows surface
    to the agent's join/lineage context, so a non-approved edge is automatically
    invisible until a human approves it (mirrors the BrainGraphEdge /
    Instruction / SemanticTable approval convention).
    One row per (organization, data_source, left_table, left_col, right_table,
    right_col). Additive — does not touch dash core.
    """
    __tablename__ = 'table_edges'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'data_source_id',
            'left_table', 'left_col', 'right_table', 'right_col',
            name='uq_table_edge_org_ds_cols',
        ),
    )

    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False, index=True)
    data_source_id = Column(String(36), ForeignKey('data_sources.id'), nullable=True, index=True)

    left_table = Column(String, nullable=False, index=True)
    left_col = Column(String, nullable=False)
    right_table = Column(String, nullable=False, index=True)
    right_col = Column(String, nullable=False)

    join_count = Column(Integer, nullable=False, default=1)
    confidence = Column(Float, nullable=False, default=0.0)

    # Provenance: 'inferred' (mined from observed joins) | 'declared' (human FK).
    source = Column(String(20), nullable=False, default='inferred')
    # 'approved' == live. Anything else (pending/rejected) is invisible to the
    # agent. Mined edges land 'pending'. Mirrors the approval convention.
    status = Column(String(20), nullable=False, default='pending', index=True)
    structured_data = Column(JSON, nullable=True)

    # Relationships
    organization = relationship("Organization")
    data_source = relationship("DataSource")

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    def __repr__(self):
        return (
            f"<TableEdge {self.left_table}.{self.left_col} <-> "
            f"{self.right_table}.{self.right_col} ({self.status})>"
        )
