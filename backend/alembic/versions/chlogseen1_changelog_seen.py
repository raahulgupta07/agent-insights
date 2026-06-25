"""changelog "last seen": add users.last_seen_changelog

Revision ID: chlogseen1
Revises: hybridsearch1
Create Date: 2026-06-25

Adds a nullable ``last_seen_changelog`` (String) column to ``users`` so the
"What's new" UI can compute an unseen badge per user. NULL means the user has
never dismissed the changelog → everything is unseen.

Plain dialect-agnostic add_column — no Postgres-only DDL needed.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "chlogseen1"
down_revision: Union[str, None] = "hybridsearch1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_seen_changelog", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_seen_changelog")
