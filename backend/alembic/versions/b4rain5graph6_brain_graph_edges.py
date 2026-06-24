"""brain graph: brain_graph_edges table (entity/correlation graph)

Phase-8 BRAIN_GRAPH (HARD RULE: AGE is dropped / not PG18-ready, so the graph is
a pgvector table + recursive-CTE traversal, NOT Apache AGE). Additive table for
directed, weighted entity/correlation edges per data source. Edges are
approval-gated: a learned/proposed edge lands as status='draft' (or 'pending')
and only goes live when flipped to status='published'. Chains off the query
library head. Inspector-guarded like the prior knowledge-layer migrations.

The `embedding` column is a pgvector ``vector`` column (no fixed pgvector cols
existed before this; we standardize on dim 1536). It is added Postgres-only and
guarded on the dialect so SQLite (unit/dev) is a clean no-op. The ``vector``
extension is already enabled by revision v1e2c3t4o5r6.

Revision ID: b4rain5graph6
Revises: q3uery4lib5
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b4rain5graph6"
down_revision: Union[str, None] = "q3uery4lib5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Embedding dimension for entity/correlation edges. No prior pgvector column
# existed in the schema; we standardize here.
_EMBED_DIM = 1536


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    is_pg = bind.dialect.name == "postgresql"

    json_type = sa.JSON()
    if is_pg:
        from sqlalchemy.dialects import postgresql
        json_type = postgresql.JSON(astext_type=sa.Text())

    if 'brain_graph_edges' not in existing:
        op.create_table(
            'brain_graph_edges',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('data_source_id', sa.String(length=36), nullable=True),
            sa.Column('src_entity', sa.String(), nullable=False),
            sa.Column('dst_entity', sa.String(), nullable=False),
            sa.Column('relation', sa.String(length=100), nullable=False, server_default='related_to'),
            sa.Column('weight', sa.Float(), nullable=False, server_default='0'),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='draft'),
            sa.Column('source', sa.String(length=50), nullable=False, server_default='manual'),
            sa.Column('structured_data', json_type, nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
            sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'organization_id', 'data_source_id', 'src_entity', 'dst_entity', 'relation',
                name='uq_brain_graph_edge_org_ds_src_dst_rel',
            ),
        )
        with op.batch_alter_table('brain_graph_edges', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_brain_graph_edges_id'), ['id'], unique=True)
            batch_op.create_index(batch_op.f('ix_brain_graph_edges_organization_id'), ['organization_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_brain_graph_edges_data_source_id'), ['data_source_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_brain_graph_edges_src_entity'), ['src_entity'], unique=False)
            # Composite index for the org+status hot path (published-only reads).
            batch_op.create_index('ix_brain_graph_edges_org_status', ['organization_id', 'status'], unique=False)

        # pgvector embedding column + ANN index — Postgres only (SQLite no-op).
        if is_pg:
            op.execute(f"ALTER TABLE brain_graph_edges ADD COLUMN embedding vector({_EMBED_DIM})")


def downgrade() -> None:
    op.drop_table('brain_graph_edges')
