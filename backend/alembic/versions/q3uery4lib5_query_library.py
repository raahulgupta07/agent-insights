"""query library: query_library_items table

Phase-3 Query Library. Additive table for saved, named, proven SQL queries
(name -> sql_text) per data source. Chains off the metrics catalog migration.
Inspector-guarded like the prior knowledge-layer migrations.

Revision ID: q3uery4lib5
Revises: m2etrics3cat4
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "q3uery4lib5"
down_revision: Union[str, None] = "m2etrics3cat4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    json_type = sa.JSON()
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql
        json_type = postgresql.JSON(astext_type=sa.Text())

    if 'query_library_items' not in existing:
        op.create_table(
            'query_library_items',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('data_source_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('sql_text', sa.Text(), nullable=False, server_default=''),
            sa.Column('tags', json_type, nullable=False, server_default='[]'),
            sa.Column('source', sa.String(length=50), nullable=False, server_default='manual'),
            sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
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
                name='uq_query_library_item_org_ds_name',
            ),
        )
        with op.batch_alter_table('query_library_items', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_query_library_items_id'), ['id'], unique=True)
            batch_op.create_index(batch_op.f('ix_query_library_items_organization_id'), ['organization_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_query_library_items_data_source_id'), ['data_source_id'], unique=False)


def downgrade() -> None:
    op.drop_table('query_library_items')
