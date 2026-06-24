"""Kepler Phase 1: governance fields on semantic tables/columns.

Additive, nullable/defaulted columns — owner / pii / freshness on semantic_tables
and pii / sensitivity on semantic_columns. All gated at runtime by
flags.HYBRID_GOVERNANCE; default behavior unchanged until enabled.

Revision ID: kepler1gov1
Revises: studio2harness1
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "kepler1gov1"
down_revision: Union[str, None] = "studio2harness1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("semantic_tables", sa.Column("owner", sa.String(), nullable=True))
    op.add_column(
        "semantic_tables",
        sa.Column("pii", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("semantic_tables", sa.Column("freshness_sla_hours", sa.Integer(), nullable=True))
    op.add_column("semantic_tables", sa.Column("last_refreshed_at", sa.DateTime(), nullable=True))

    op.add_column(
        "semantic_columns",
        sa.Column("pii", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "semantic_columns",
        sa.Column("sensitivity", sa.String(length=20), nullable=False, server_default="none"),
    )


def downgrade() -> None:
    op.drop_column("semantic_columns", "sensitivity")
    op.drop_column("semantic_columns", "pii")
    op.drop_column("semantic_tables", "last_refreshed_at")
    op.drop_column("semantic_tables", "freshness_sla_hours")
    op.drop_column("semantic_tables", "pii")
    op.drop_column("semantic_tables", "owner")
