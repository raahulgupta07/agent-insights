"""Pipeline v1 (P3, HYBRID_DEF_REGISTRY): the Definition Registry.

A single source of truth for an org/agent's business definitions — a metric, a
named filter, or a global rule — each carrying the SQL predicate that implements
it AND the expected ground-truth answer it must reproduce. Goldens, instructions
and chat answers all REFERENCE a definition, so correcting one row regenerates
every dependent query (the correction loop, P6).

Born ``status='pending'`` behind the existing review gate. Additive table; no
existing model is touched.
"""
from __future__ import annotations

from sqlalchemy import Column, String, Text, JSON, Index

from app.models.base import BaseSchema


class AgentDefinition(BaseSchema):
    __tablename__ = "agent_definitions"
    __table_args__ = (
        Index("ix_agent_def_org_ds", "organization_id", "data_source_id"),
        Index("ix_agent_def_name", "organization_id", "name"),
    )

    organization_id = Column(String(36), nullable=False, index=True)
    # optional scoping — a def can be org-wide, per-source, or per-agent.
    data_source_id = Column(String(36), nullable=True, index=True)
    studio_id = Column(String(36), nullable=True, index=True)

    # 'Lead', 'New User', 'Successful Calls', 'status_rule' ...
    name = Column(String, nullable=False)
    # 'metric' (countable thing), 'filter' (named predicate), 'rule' (always-on)
    kind = Column(String(20), nullable=False, default="metric")

    # the SQL predicate that implements it, e.g.
    #   "Status"='Completed' AND "Call Outcome"='Unsuccessful' AND "...Type"='Lead'
    # For kind='ratio' this is the NUMERATOR predicate; den_predicate is the denominator.
    sql_predicate = Column(Text, nullable=False, default="")
    # ratio metrics (kind='ratio', flag RATIO_METRICS): the DENOMINATOR predicate; rate
    # = numerator_count / denominator_count. '' for non-ratio defs.
    den_predicate = Column(Text, nullable=False, default="")
    # group-by dimensions for breakdown answers, [{column, op:'groupby', value}]. [] flat.
    group_by = Column(JSON, nullable=False, default=list)
    # parsed filters [{column, op, value}] from the logic doc (provenance)
    filters = Column(JSON, nullable=False, default=list)
    # columns the predicate references (for dependency lookup in the correction loop)
    columns_used = Column(JSON, nullable=False, default=list)

    # ground-truth answers: [{"scope": "total", "value": 1544}, ...]
    expected = Column(JSON, nullable=False, default=list)

    # human description / the original logic text + where it came from
    description = Column(Text, nullable=False, default="")
    logic_text = Column(Text, nullable=False, default="")
    source_doc = Column(String, nullable=True)

    # pending | approved | rejected — same review gate as the rest of the hybrid layer
    status = Column(String(20), nullable=False, default="pending")
