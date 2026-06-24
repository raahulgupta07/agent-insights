"""hybrid Phase S1.2: skill frontmatter columns

Adds Claude-style SKILL.md frontmatter fields to the skills table:
allowed_tools / disallowed_tools (JSON-encoded lists), disable_model_invocation
and user_invocable (booleans with safe server_defaults so existing rows are
unchanged), skill_metadata (JSON dict) and license. Dialect-agnostic (plain
add_column / drop_column — works on SQLite + Postgres, no schema qualifier).

Revision ID: sk2frontmttr1
Revises: b4rain5graph6
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sk2frontmttr1"
down_revision: Union[str, None] = "b4rain5graph6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("allowed_tools", sa.Text(), nullable=True))
    op.add_column("skills", sa.Column("disallowed_tools", sa.Text(), nullable=True))
    op.add_column(
        "skills",
        sa.Column(
            "disable_model_invocation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "skills",
        sa.Column(
            "user_invocable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column("skills", sa.Column("skill_metadata", sa.Text(), nullable=True))
    op.add_column("skills", sa.Column("license", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("skills", "license")
    op.drop_column("skills", "skill_metadata")
    op.drop_column("skills", "user_invocable")
    op.drop_column("skills", "disable_model_invocation")
    op.drop_column("skills", "disallowed_tools")
    op.drop_column("skills", "allowed_tools")
