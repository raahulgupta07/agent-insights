from sqlalchemy import Column, String, Text, ForeignKey, JSON, UniqueConstraint, Boolean, Integer, DateTime
from sqlalchemy.orm import relationship

from app.models.base import BaseSchema


class SemanticTable(BaseSchema):
    """Per-table semantic meaning for a data source (Phase-1 Semantic Layer).

    Stores human/AI-curated meaning for a table: a free-text description, a list
    of use cases, quality notes, and a draft/published status. One row per
    (organization, data_source, table_name). Additive — does not touch bow's
    schema store (ConnectionTable / DataSourceTable), which remains the source
    of truth for actual columns/types.
    """
    __tablename__ = 'semantic_tables'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'data_source_id', 'table_name',
            name='uq_semantic_table_org_ds_name',
        ),
    )

    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False, index=True)
    data_source_id = Column(String(36), ForeignKey('data_sources.id'), nullable=False, index=True)
    table_name = Column(String, nullable=False)

    description = Column(Text, nullable=False, default='')
    use_cases = Column(JSON, nullable=False, default=list)
    quality_notes = Column(JSON, nullable=False, default=list)
    status = Column(String(50), nullable=False, default='draft')

    # --- Governance (Kepler Phase 1, gated HYBRID_GOVERNANCE) ---------------
    # Owner = accountable human/team (free text). PII = table holds personal
    # data. freshness_sla_hours = max age before "stale". last_refreshed_at =
    # data-as-of (auto from data_source sync when null). All nullable/additive.
    owner = Column(String, nullable=True)
    pii = Column(Boolean, nullable=False, default=False)
    freshness_sla_hours = Column(Integer, nullable=True)
    last_refreshed_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization")
    data_source = relationship("DataSource")
    columns = relationship(
        "SemanticColumn",
        back_populates="semantic_table",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def described(self) -> bool:
        return bool(self.description and self.description.strip())


class SemanticColumn(BaseSchema):
    """Per-column semantic meaning under a SemanticTable."""
    __tablename__ = 'semantic_columns'
    __table_args__ = (
        UniqueConstraint(
            'semantic_table_id', 'name',
            name='uq_semantic_column_table_name',
        ),
    )

    semantic_table_id = Column(
        String(36),
        ForeignKey('semantic_tables.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False)
    type = Column(String, nullable=False, default='')
    meaning = Column(Text, nullable=False, default='')
    status = Column(String(50), nullable=False, default='draft')

    # --- Governance (Kepler Phase 1) ---
    pii = Column(Boolean, nullable=False, default=False)
    sensitivity = Column(String(20), nullable=False, default='none')  # none|internal|pii|secret

    semantic_table = relationship("SemanticTable", back_populates="columns")
