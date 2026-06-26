"""user-owned groups: add groups.owner_user_id

Revision ID: usergroups1
Revises: agentchan1
Create Date: 2026-06-26

Hybrid user-owned groups (HYBRID_USER_GROUPS, default OFF). Adds a nullable
``owner_user_id`` FK to the existing ``groups`` table so a normal user can own
a personal group used as a reusable share target. NULL = an org / admin / LDAP
group (unchanged upstream behavior). The existing (organization_id, name)
unique constraint is intentionally left untouched.

Additive + nullable, so the column is inert until the feature is on.
Dialect-agnostic; works on both Postgres and SQLite.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "usergroups1"
down_revision: Union[str, None] = "agentchan1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "groups",
        sa.Column(
            "owner_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_groups_owner_user_id", "groups", ["owner_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_groups_owner_user_id", table_name="groups")
    op.drop_column("groups", "owner_user_id")
