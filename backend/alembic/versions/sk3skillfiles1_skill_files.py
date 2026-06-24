"""hybrid Phase S3.1: skill_files (L3 bundled skill resources) table

Stores files shipped alongside a Skill's SKILL.md body: executable scripts,
on-demand reference docs, or assets. content holds inline text OR an "s3:<key>"
pointer. Soft-deleted via deleted_at. Reuse/visibility gated by flags.SKILLS.
Dialect-agnostic (plain table — works on SQLite + Postgres, no schema qualifier).

Revision ID: sk3skillfiles1
Revises: sk2frontmttr1
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sk3skillfiles1"
down_revision: Union[str, None] = "sk2frontmttr1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="reference"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_files_id", "skill_files", ["id"])
    op.create_index("ix_skill_files_skill_id", "skill_files", ["skill_id"])
    op.create_index("ix_skillfile_skill", "skill_files", ["skill_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_skillfile_skill", table_name="skill_files")
    op.drop_index("ix_skill_files_skill_id", table_name="skill_files")
    op.drop_index("ix_skill_files_id", table_name="skill_files")
    op.drop_table("skill_files")
