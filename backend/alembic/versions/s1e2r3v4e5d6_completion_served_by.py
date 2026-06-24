"""hybrid serving-funnel: completion served_by + elapsed_ms

Adds two nullable columns to the completions table so each completion records
which serving tier answered it (reasoning_cache / answer_cache / materialized /
agent_loop) and its end-to-end latency in milliseconds. Both nullable so no
backfill is required. Dialect-agnostic (plain add_column — works on SQLite +
Postgres, no schema qualifier).

Revision ID: s1e2r3v4e5d6
Revises: q1c2a3c4h5e6
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s1e2r3v4e5d6"
down_revision: Union[str, None] = "q1c2a3c4h5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("completions", sa.Column("served_by", sa.String(), nullable=True))
    op.add_column("completions", sa.Column("elapsed_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("completions", "elapsed_ms")
    op.drop_column("completions", "served_by")
