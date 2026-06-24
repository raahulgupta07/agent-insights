"""Kepler Phase 2: code_cache (proven generate_df code memory).

New table mirroring query_cache for the python-pandas agent. Gated at runtime by
flags.CODE_BANK; injected as context only, never executed.

Revision ID: kepler2cb1
Revises: kepler1gov1
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "kepler2cb1"
down_revision: Union[str, None] = "kepler1gov1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "code_cache",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("question_norm", sa.Text(), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="chat"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_cache_organization_id", "code_cache", ["organization_id"])
    op.create_index("ix_code_cache_data_source_id", "code_cache", ["data_source_id"])
    op.create_index("ix_code_cache_question_hash", "code_cache", ["question_hash"])
    op.create_index("ix_code_cache_status", "code_cache", ["status"])
    op.create_index(
        "ix_code_cache_lookup", "code_cache",
        ["organization_id", "data_source_id", "question_hash", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_code_cache_lookup", table_name="code_cache")
    op.drop_index("ix_code_cache_status", table_name="code_cache")
    op.drop_index("ix_code_cache_question_hash", table_name="code_cache")
    op.drop_index("ix_code_cache_data_source_id", table_name="code_cache")
    op.drop_index("ix_code_cache_organization_id", table_name="code_cache")
    op.drop_table("code_cache")
