"""dashboard layout versioning metadata: change_summary, source, created_by_user_id

Revision ID: dashversions1
Revises: skillorigin1
Create Date: 2026-06-23

Adds versioning provenance to dashboard_layout_versions so a deliberate
"snapshot a NEW version" path (add/remove chart from chat, manual remove,
autopilot, restore) can record WHY a new immutable version was created and by
whom. Additive + nullable; the existing in-place mutate path is unaffected.
Dialect-safe (plain ADD COLUMN; works on PG + SQLite).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dashversions1"
down_revision: Union[str, None] = "skillorigin1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dashboard_layout_versions",
        sa.Column("change_summary", sa.String(), nullable=True),
    )
    op.add_column(
        "dashboard_layout_versions",
        sa.Column("source", sa.String(), nullable=True),
    )
    op.add_column(
        "dashboard_layout_versions",
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dashboard_layout_versions", "created_by_user_id")
    op.drop_column("dashboard_layout_versions", "source")
    op.drop_column("dashboard_layout_versions", "change_summary")
