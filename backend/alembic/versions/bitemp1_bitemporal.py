"""bi-temporal columns: valid_at / invalid_at / superseded_by

Revision ID: bitemp1
Revises: agentmem1
Create Date: 2026-06-21

Adds a fact timeline to evolving-fact tables (metric_definitions, semantic_tables,
agent_memories). Additive + nullable -> existing rows are all "current"
(invalid_at IS NULL). Flag-gated at runtime (HYBRID_BITEMPORAL); reads only filter
on these when the flag is on, so OFF == prior behavior. Works on PG + SQLite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bitemp1"
down_revision: Union[str, None] = "agentmem1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("metric_definitions", "semantic_tables", "agent_memories")


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("valid_at", sa.DateTime(), nullable=True))
        op.add_column(t, sa.Column("invalid_at", sa.DateTime(), nullable=True))
        op.add_column(t, sa.Column("superseded_by", sa.String(length=36), nullable=True))
        op.create_index(f"ix_{t}_invalid_at", t, ["invalid_at"])


def downgrade() -> None:
    for t in _TABLES:
        op.drop_index(f"ix_{t}_invalid_at", table_name=t)
        op.drop_column(t, "superseded_by")
        op.drop_column(t, "invalid_at")
        op.drop_column(t, "valid_at")
