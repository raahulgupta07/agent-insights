"""agent_definitions: ratio metric columns (P8 RATIO_METRICS)

Revision ID: ratiodef1
Revises: defreg1
Create Date: 2026-07-01

Adds den_predicate (denominator SQL for kind='ratio') + group_by (breakdown dims).
kind='ratio' reuses the existing `kind` column. Additive, idempotent (IF NOT EXISTS),
PG-guarded — safe on a DB where the columns may already exist.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "ratiodef1"
down_revision: Union[str, None] = "defreg1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE agent_definitions "
        "ADD COLUMN IF NOT EXISTS den_predicate text NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE agent_definitions "
        "ADD COLUMN IF NOT EXISTS group_by json NOT NULL DEFAULT '[]'::json"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE agent_definitions DROP COLUMN IF EXISTS group_by")
    op.execute("ALTER TABLE agent_definitions DROP COLUMN IF EXISTS den_predicate")
