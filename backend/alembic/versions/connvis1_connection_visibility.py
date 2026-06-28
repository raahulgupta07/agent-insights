"""connector 3-level visibility: add connections.visibility

Revision ID: connvis1
Revises: agentconn1
Create Date: 2026-06-28

3-level connector VISIBILITY model on the existing ``connections`` table:
  'private' = owner only.
  'shared'  = owner + specifically-granted users/groups (resource_grants).
  'org'     = all org members.
owner_user_id is now ALWAYS the creator (keeps edit rights) regardless of level.

Adds one NOT NULL column (server_default 'private' so existing rows are inert /
back-compatible) + an index, then back-fills legacy admin-made org-wide rows
(owner_user_id IS NULL) to visibility='org' to preserve their prior behavior.

Additive — the column is inert until the feature writes a non-default value.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "connvis1"
down_revision: Union[str, None] = "agentconn1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column(
            "visibility",
            sa.String(length=16),
            nullable=False,
            server_default="private",
        ),
    )
    op.create_index(
        "ix_connections_visibility", "connections", ["visibility"]
    )
    # Legacy org-wide connectors (admin-made, owner_user_id NULL) keep their
    # everyone-can-see behavior under the new model.
    op.execute(
        "UPDATE connections SET visibility = 'org' WHERE owner_user_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_connections_visibility", table_name="connections")
    op.drop_column("connections", "visibility")
