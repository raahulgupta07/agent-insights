"""per-agent private connectors: add connections.owner_user_id + studio_id

Revision ID: agentconn1
Revises: usergroups1
Create Date: 2026-06-26

Per-agent PRIVATE connectors (HYBRID_AGENT_CONNECTORS, default OFF). Adds two
nullable FK columns to the existing ``connections`` table:
  owner_user_id -> users.id   = private to that user.
  studio_id     -> studios.id = bound to one agent/studio (CASCADE delete).
NULL/NULL = an org-wide connector (unchanged upstream behavior).

Additive + nullable, so the columns are inert until the feature is on.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "agentconn1"
down_revision: Union[str, None] = "usergroups1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "connections",
        sa.Column("studio_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_connections_owner_user_id", "connections", ["owner_user_id"]
    )
    op.create_index(
        "ix_connections_studio_id", "connections", ["studio_id"]
    )
    op.create_foreign_key(
        "fk_connections_owner_user_id",
        "connections",
        "users",
        ["owner_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_connections_studio_id",
        "connections",
        "studios",
        ["studio_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_connections_studio_id", "connections", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_connections_owner_user_id", "connections", type_="foreignkey"
    )
    op.drop_index("ix_connections_studio_id", table_name="connections")
    op.drop_index("ix_connections_owner_user_id", table_name="connections")
    op.drop_column("connections", "studio_id")
    op.drop_column("connections", "owner_user_id")
