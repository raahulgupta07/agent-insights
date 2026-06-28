"""reports.session_summary: heal the missing Session Summary column

Revision ID: sessumm1
Revises: connvis1
Create Date: 2026-06-28

The Session Summary feature (v1.48-1.49) added ``Report.session_summary``
(JSON, nullable) to the ORM model but shipped NO alembic migration — the
column was only hand-applied to the live DB via raw DDL. Any schema rebuilt
purely from migrations (a fresh install, or a DROP SCHEMA / wipe) therefore
lacks the column, and every report query then 500s with
``UndefinedColumnError: column reports.session_summary does not exist`` —
blocking report + completion creation entirely (chat/file analysis dead).

This migration creates the column so fresh installs match the model.

Idempotent: uses ADD COLUMN IF NOT EXISTS so it is safe on legacy DBs that
already received the column via the manual DDL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "sessumm1"
down_revision: Union[str, None] = "connvis1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS: legacy DBs already have it via hand-applied DDL; fresh DBs don't.
    op.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS session_summary json")


def downgrade() -> None:
    op.execute("ALTER TABLE reports DROP COLUMN IF EXISTS session_summary")
