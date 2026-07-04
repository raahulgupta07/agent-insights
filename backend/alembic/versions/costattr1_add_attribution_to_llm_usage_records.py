"""add attribution columns to llm_usage_records

Revision ID: costattr1
Revises: rbacbf01
Create Date: 2026-07-04 00:00:00.000000

Adds organization_id / user_id / report_id / data_source_id to llm_usage_records
so the Cost console can break LLM token spend down by user, agent (data source)
and group over time. All columns are nullable: org_id is populated on every new
record (from the model's org), the rest are best-effort from the agent run
context (the usage-attribution contextvar stamped by AgentV2). Rows written
before this migration stay NULL and surface as an "Unattributed" bucket in the
cost views.

Indexes: one per attribution column (for the per-dimension group-bys) plus a
composite (organization_id, created_at) matching the Cost console's org + date
range scan.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'costattr1'
down_revision: Union[str, None] = 'rbacbf01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('llm_usage_records', sa.Column('organization_id', sa.String(), nullable=True))
    op.add_column('llm_usage_records', sa.Column('user_id', sa.String(), nullable=True))
    op.add_column('llm_usage_records', sa.Column('report_id', sa.String(), nullable=True))
    op.add_column('llm_usage_records', sa.Column('data_source_id', sa.String(), nullable=True))

    op.create_index('ix_llm_usage_records_organization_id', 'llm_usage_records', ['organization_id'])
    op.create_index('ix_llm_usage_records_user_id', 'llm_usage_records', ['user_id'])
    op.create_index('ix_llm_usage_records_report_id', 'llm_usage_records', ['report_id'])
    op.create_index('ix_llm_usage_records_data_source_id', 'llm_usage_records', ['data_source_id'])

    # Composite index matching the Cost console's org + date-range scan. PG-only
    # (SQLite is fine without it; the per-column indexes above already cover it).
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            'ix_llm_usage_records_org_created',
            'llm_usage_records',
            ['organization_id', 'created_at'],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index('ix_llm_usage_records_org_created', table_name='llm_usage_records')

    op.drop_index('ix_llm_usage_records_data_source_id', table_name='llm_usage_records')
    op.drop_index('ix_llm_usage_records_report_id', table_name='llm_usage_records')
    op.drop_index('ix_llm_usage_records_user_id', table_name='llm_usage_records')
    op.drop_index('ix_llm_usage_records_organization_id', table_name='llm_usage_records')

    op.drop_column('llm_usage_records', 'data_source_id')
    op.drop_column('llm_usage_records', 'report_id')
    op.drop_column('llm_usage_records', 'user_id')
    op.drop_column('llm_usage_records', 'organization_id')
