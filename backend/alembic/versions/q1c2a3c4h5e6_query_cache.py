"""hybrid Phase 4/5: query_cache (reasoning-cache) table

Stores proven read-only SELECTs keyed by normalized-question hash + data-source
scope. Read path (BRAIN_READ) injects them as PROVEN QUERIES; write path
(QUERY_CACHE) captures them; rows land status='pending' until the approval gate
promotes to 'active'. Dialect-agnostic (plain table — works on SQLite + Postgres).

Revision ID: q1c2a3c4h5e6
Revises: h1y2b3r4i5d6
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q1c2a3c4h5e6"
down_revision: Union[str, None] = "h1y2b3r4i5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "query_cache",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("question_norm", sa.Text(), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="chat"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("thumbs_down", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_query_cache_organization_id", "query_cache", ["organization_id"])
    op.create_index("ix_query_cache_data_source_id", "query_cache", ["data_source_id"])
    op.create_index("ix_query_cache_question_hash", "query_cache", ["question_hash"])
    op.create_index("ix_query_cache_status", "query_cache", ["status"])
    op.create_index(
        "ix_query_cache_lookup",
        "query_cache",
        ["organization_id", "data_source_id", "question_hash", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_query_cache_lookup", table_name="query_cache")
    op.drop_index("ix_query_cache_status", table_name="query_cache")
    op.drop_index("ix_query_cache_question_hash", table_name="query_cache")
    op.drop_index("ix_query_cache_data_source_id", table_name="query_cache")
    op.drop_index("ix_query_cache_organization_id", table_name="query_cache")
    op.drop_table("query_cache")
