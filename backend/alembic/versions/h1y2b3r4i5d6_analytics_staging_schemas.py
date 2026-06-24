"""hybrid Phase 2: create analytics + staging schemas (Postgres only)

Agent-owned schemas in dash's managed Postgres:
- analytics: Engineer-built reusable views / summary tables
- staging:   ingested snapshots for federation/materialization

SQLite (dev/test default) has no schemas — skipped there.

Revision ID: h1y2b3r4i5d6
Revises: d6d9a78b7b4a
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "h1y2b3r4i5d6"
down_revision: Union[str, None] = "d6d9a78b7b4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    op.execute("CREATE SCHEMA IF NOT EXISTS staging")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    op.execute("DROP SCHEMA IF EXISTS analytics CASCADE")
