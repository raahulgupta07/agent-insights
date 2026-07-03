from sqlalchemy import Column, String, Integer, Text, JSON, Index
from app.models.base import BaseSchema


class AnalysisWorkflow(BaseSchema):
    """A saved, reusable, parameterized analysis (Workflows v2 — HYBRID_WORKFLOWS_V2).

    A user finishes an analysis in a report and SAVES it as a workflow: the
    report's data-turn step plan (the ordered analysis prompts) is captured into
    ``steps_json`` and any ``{placeholder}`` tokens in those prompts become the
    workflow's ``params_schema_json``. Anyone (per ``scope``) can then REPLAY the
    workflow from the composer with concrete params, and the same steps run
    headless so the analysis is consistent for every user (OpenAI data-agent
    "workflows": weekly reports, table validations).

    No FK constraints by design (same convention as agent_knowledge /
    column_profiles — an additive feature table, avoids delete-cascade coupling).
    """

    __tablename__ = "analysis_workflows"
    __table_args__ = (
        Index("ix_analysis_workflows_org", "organization_id"),
        Index("ix_analysis_workflows_owner", "organization_id", "owner_user_id"),
    )

    organization_id = Column(String(36), nullable=False)
    owner_user_id = Column(String(36), nullable=True)

    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)

    # steps_json: {"steps":[{"n":1,"prompt":"...","source_completion_id":...}],
    #              "source_report_id":..., "result_columns":[...]}
    steps_json = Column(JSON, nullable=True)
    # params_schema_json: {"params":[{"name":"period","label":"Period","required":true}]}
    params_schema_json = Column(JSON, nullable=True)

    # 'private' (owner only) | 'org' (all members)
    scope = Column(String(16), nullable=False, default="private", server_default="private")

    run_count = Column(Integer, nullable=False, default=0, server_default="0")

    # 'active' | 'archived'
    status = Column(String(16), nullable=False, default="active", server_default="active")
