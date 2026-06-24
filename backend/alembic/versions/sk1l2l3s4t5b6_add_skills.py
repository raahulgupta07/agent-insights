"""hybrid Phase 6: skills (self-service Skills) table

Stores Claude-style SKILL.md capabilities with progressive disclosure. L1
catalog = name + description; L2 = full skill_md body loaded on demand. Scoped
personal / org / global; visible only when status='active'. Visibility +
authoring are gated by flags.SKILLS. Dialect-agnostic (plain table — works on
SQLite + Postgres, no schema qualifier).

Revision ID: sk1l2l3s4t5b6
Revises: s1e2r3v4e5d6
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sk1l2l3s4t5b6"
down_revision: Union[str, None] = "s1e2r3v4e5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False, server_default="personal"),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("skill_md", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skills_id", "skills", ["id"])
    op.create_index("ix_skills_name", "skills", ["name"])
    op.create_index("ix_skills_scope", "skills", ["scope"])
    op.create_index("ix_skills_owner_user_id", "skills", ["owner_user_id"])
    op.create_index("ix_skills_organization_id", "skills", ["organization_id"])
    op.create_index(
        "ix_skill_visibility",
        "skills",
        ["organization_id", "scope", "status"],
    )
    op.create_index(
        "ix_skill_owner",
        "skills",
        ["owner_user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_skill_owner", table_name="skills")
    op.drop_index("ix_skill_visibility", table_name="skills")
    op.drop_index("ix_skills_organization_id", table_name="skills")
    op.drop_index("ix_skills_owner_user_id", table_name="skills")
    op.drop_index("ix_skills_scope", table_name="skills")
    op.drop_index("ix_skills_name", table_name="skills")
    op.drop_index("ix_skills_id", table_name="skills")
    op.drop_table("skills")
