"""skill origin column: manual vs auto (👍 auto-proposed)

Revision ID: skillorigin1
Revises: skillbitemp1
Create Date: 2026-06-21

Records whether a skill was hand-authored ('manual') or auto-proposed via 👍
feedback ('auto'). Additive + nullable, server_default 'manual' -> every
existing row reads 'manual' (the prior, hand-authored reality). Dialect-safe
(plain ADD COLUMN; works on PG + SQLite). Surfaced read-only; no behavior gate
of its own.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "skillorigin1"
down_revision: Union[str, None] = "skillbitemp1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("origin", sa.String(length=20), nullable=True, server_default="manual"),
    )


def downgrade() -> None:
    op.drop_column("skills", "origin")
