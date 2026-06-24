"""hybrid Tier-1: answer_cache (final-answer reuse) table

Stores fully-rendered answers (markdown + row-count summary) keyed by a
normalized-question hash + data-source scope, with an optional TTL (expires_at;
NULL = never expires). Lets the serving funnel return a cached answer directly
instead of re-running the whole plan/execute/reflect loop. No approval gate —
this caches the agent's own validated output. Reuse is gated by
flags.ANSWER_CACHE. Dialect-agnostic (plain table — works on SQLite + Postgres,
no schema qualifier).

Revision ID: aac1c2c3c4c5
Revises: sk1l2l3s4t5b6
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "aac1c2c3c4c5"
down_revision: Union[str, None] = "sk1l2l3s4t5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "answer_cache",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("question_norm", sa.Text(), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("answer_md", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sql_text", sa.Text(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_answer_cache_id", "answer_cache", ["id"])
    op.create_index("ix_answer_cache_organization_id", "answer_cache", ["organization_id"])
    op.create_index("ix_answer_cache_data_source_id", "answer_cache", ["data_source_id"])
    op.create_index("ix_answer_cache_question_hash", "answer_cache", ["question_hash"])
    op.create_index(
        "ix_answer_cache_lookup",
        "answer_cache",
        ["organization_id", "question_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_answer_cache_lookup", table_name="answer_cache")
    op.drop_index("ix_answer_cache_question_hash", table_name="answer_cache")
    op.drop_index("ix_answer_cache_data_source_id", table_name="answer_cache")
    op.drop_index("ix_answer_cache_organization_id", table_name="answer_cache")
    op.drop_index("ix_answer_cache_id", table_name="answer_cache")
    op.drop_table("answer_cache")
