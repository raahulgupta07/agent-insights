"""knowledge layer scaffold: semantic table/column + metric definition tables

Empty scaffold migration chaining off the pgvector head. All DDL for the
semantic knowledge layer will be added in Phase 1 under HYBRID_SEMANTIC_LAYER
and HYBRID_METRICS_CATALOG flags. Nothing is created here.

Revision ID: k1nowl2edge3
Revises: v1e2c3t4o5r6
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "k1nowl2edge3"
down_revision: Union[str, None] = "v1e2c3t4o5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if 'semantic_tables' not in existing:
        op.create_table(
            'semantic_tables',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('data_source_id', sa.String(length=36), nullable=False),
            sa.Column('table_name', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('use_cases', sa.JSON(), nullable=False),
            sa.Column('quality_notes', sa.JSON(), nullable=False),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='draft'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
            sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'organization_id', 'data_source_id', 'table_name',
                name='uq_semantic_table_org_ds_name',
            ),
        )
        with op.batch_alter_table('semantic_tables', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_semantic_tables_id'), ['id'], unique=True)
            batch_op.create_index(batch_op.f('ix_semantic_tables_organization_id'), ['organization_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_semantic_tables_data_source_id'), ['data_source_id'], unique=False)

    if 'semantic_columns' not in existing:
        op.create_table(
            'semantic_columns',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('semantic_table_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('type', sa.String(), nullable=False, server_default=''),
            sa.Column('meaning', sa.Text(), nullable=False, server_default=''),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='draft'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ['semantic_table_id'], ['semantic_tables.id'], ondelete='CASCADE',
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'semantic_table_id', 'name',
                name='uq_semantic_column_table_name',
            ),
        )
        with op.batch_alter_table('semantic_columns', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_semantic_columns_id'), ['id'], unique=True)
            batch_op.create_index(batch_op.f('ix_semantic_columns_semantic_table_id'), ['semantic_table_id'], unique=False)


def downgrade() -> None:
    op.drop_table('semantic_columns')
    op.drop_table('semantic_tables')
