"""skill_runs: track every execution of a skill's bundled script (per user).

One new table ``skill_runs`` — one row per run of a Skill's bundled script
(e.g. ``scripts/cohort.py``). Records the running user/org, the script path,
lifecycle status (running|success|error|blocked), result row count, captured
stdout/error, an optional result pointer, and start/finish timestamps. Additive;
default behavior unchanged until consumed.

Revision ID: skillrun1
Revises: docknow1
Create Date: 2026-06-20 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "skillrun1"
down_revision: Union[str, None] = "docknow1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_ref", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_runs_skill_id", "skill_runs", ["skill_id"])
    op.create_index("ix_skill_runs_owner_user_id", "skill_runs", ["owner_user_id"])
    op.create_index("ix_skill_runs_organization_id", "skill_runs", ["organization_id"])
    op.create_index("ix_skillrun_owner", "skill_runs", ["owner_user_id", "status"])
    op.create_index("ix_skillrun_skill", "skill_runs", ["skill_id"])


def downgrade() -> None:
    op.drop_index("ix_skillrun_skill", table_name="skill_runs")
    op.drop_index("ix_skillrun_owner", table_name="skill_runs")
    op.drop_index("ix_skill_runs_organization_id", table_name="skill_runs")
    op.drop_index("ix_skill_runs_owner_user_id", table_name="skill_runs")
    op.drop_index("ix_skill_runs_skill_id", table_name="skill_runs")
    op.drop_table("skill_runs")
