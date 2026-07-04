"""add reports.last_activity_at for activity-based sidebar sort (#479)

Revision ID: sidesort1
Revises: fileref1
Create Date: 2026-07-04 00:00:00.000000

Adds ``reports.last_activity_at`` — a denormalized "last conversation activity"
timestamp used to sort the report sidebar by real chat activity instead of
creation time. It is bumped at two choke points (see completion_service +
agent_v2): when a new user message is created and when an agent turn finalizes.
It is intentionally distinct from ``updated_at`` (which bumps on any metadata
edit — rename / theme / sharing).

Read path is gated behind ``HYBRID_SIDEBAR_ACTIVITY_SORT`` (default OFF) — the
column + bumps are additive and inert until the flag is on.

Existing rows are backfilled to their own ``created_at`` so ordering is sane
immediately. Idempotent: guarded by a column-existence check so a re-run /
already-patched DB is safe (mirrors the fork's other repair-style migrations).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'sidesort1'
down_revision: Union[str, None] = 'fileref1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspector.get_columns(table))
    except Exception:
        return False


def _has_index(inspector, table: str, index: str) -> bool:
    try:
        return any(ix["name"] == index for ix in inspector.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "reports", "last_activity_at"):
        op.add_column(
            "reports",
            sa.Column("last_activity_at", sa.DateTime(), nullable=True),
        )
        # Backfill so existing rows sort sanely immediately.
        op.execute("UPDATE reports SET last_activity_at = created_at")

    if not _has_index(inspector, "reports", "ix_reports_last_activity_at"):
        try:
            op.create_index(
                "ix_reports_last_activity_at", "reports", ["last_activity_at"]
            )
        except Exception:
            # Index already exists / concurrent create — safe to skip.
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "reports", "ix_reports_last_activity_at"):
        try:
            op.drop_index("ix_reports_last_activity_at", table_name="reports")
        except Exception:
            pass
    if _has_column(inspector, "reports", "last_activity_at"):
        op.drop_column("reports", "last_activity_at")
