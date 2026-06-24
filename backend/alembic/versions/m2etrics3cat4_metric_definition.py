"""metrics catalog: metric_definitions table

Phase-1 Metrics Catalog. Additive table for named business metrics
(name -> definition -> sql_calc) per data source. Chains off the knowledge
layer scaffold. Inspector-guarded like the scaffold migration.

Revision ID: m2etrics3cat4
Revises: k1nowl2edge3
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "m2etrics3cat4"
down_revision: Union[str, None] = "k1nowl2edge3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if 'metric_definitions' not in existing:
        op.create_table(
            'metric_definitions',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('data_source_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('definition', sa.Text(), nullable=False, server_default=''),
            sa.Column('table_ref', sa.String(), nullable=False, server_default=''),
            sa.Column('sql_calc', sa.Text(), nullable=False, server_default=''),
            sa.Column('owner', sa.String(), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='draft'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
            sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'organization_id', 'data_source_id', 'name',
                name='uq_metric_definition_org_ds_name',
            ),
        )
        with op.batch_alter_table('metric_definitions', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_metric_definitions_id'), ['id'], unique=True)
            batch_op.create_index(batch_op.f('ix_metric_definitions_organization_id'), ['organization_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_metric_definitions_data_source_id'), ['data_source_id'], unique=False)


def downgrade() -> None:
    op.drop_table('metric_definitions')
