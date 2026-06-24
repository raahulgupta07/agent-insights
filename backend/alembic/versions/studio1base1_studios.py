"""hybrid Studios ST1: studios + studio_members + studio_data_sources +
studio_skills + studio_artifacts tables, plus reports.studio_id column.

NotebookLM-style shareable agent containers. ALL NEW tables — no change to the
`data_sources`/`agent` subsystem; studio_data_sources merely references it.
reports.studio_id is a nullable FK so existing/upstream reports are unaffected.
All Studios behavior is gated by flags.STUDIOS and defaults OFF.

Dialect-agnostic (plain tables — works on SQLite + Postgres, no schema qualifier).

Revision ID: studio1base1
Revises: sk3skillfiles1
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "studio1base1"
down_revision: Union[str, None] = "sk3skillfiles1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- studios -----------------------------------------------------------
    op.create_table(
        "studios",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("persona", sa.Text(), nullable=True),
        sa.Column("avatar", sa.String(), nullable=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("share_scope", sa.String(), nullable=False, server_default="private"),
        sa.Column("share_token", sa.String(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studios_id", "studios", ["id"])
    op.create_index("ix_studios_name", "studios", ["name"])
    op.create_index("ix_studios_owner_user_id", "studios", ["owner_user_id"])
    op.create_index("ix_studios_organization_id", "studios", ["organization_id"])
    op.create_index("ix_studios_share_token", "studios", ["share_token"], unique=True)
    op.create_index("ix_studio_org_owner", "studios", ["organization_id", "owner_user_id"])

    # --- studio_data_sources ----------------------------------------------
    op.create_table(
        "studio_data_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_data_sources_id", "studio_data_sources", ["id"])
    op.create_index("ix_studio_data_sources_studio_id", "studio_data_sources", ["studio_id"])
    op.create_index("ix_studio_data_sources_agent_id", "studio_data_sources", ["agent_id"])
    op.create_index("ix_studio_ds_studio", "studio_data_sources", ["studio_id", "agent_id"])

    # --- studio_members ----------------------------------------------------
    op.create_table(
        "studio_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_members_id", "studio_members", ["id"])
    op.create_index("ix_studio_members_studio_id", "studio_members", ["studio_id"])
    op.create_index("ix_studio_members_user_id", "studio_members", ["user_id"])
    op.create_index("ix_studio_member_studio", "studio_members", ["studio_id", "user_id"])

    # --- studio_skills -----------------------------------------------------
    op.create_table(
        "studio_skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_skills_id", "studio_skills", ["id"])
    op.create_index("ix_studio_skills_studio_id", "studio_skills", ["studio_id"])
    op.create_index("ix_studio_skills_skill_id", "studio_skills", ["skill_id"])
    op.create_index("ix_studio_skill_studio", "studio_skills", ["studio_id", "skill_id"])

    # --- studio_artifacts --------------------------------------------------
    op.create_table(
        "studio_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_artifacts_id", "studio_artifacts", ["id"])
    op.create_index("ix_studio_artifacts_studio_id", "studio_artifacts", ["studio_id"])
    op.create_index("ix_studio_artifact_studio", "studio_artifacts", ["studio_id", "kind"])

    # --- reports.studio_id -------------------------------------------------
    op.add_column("reports", sa.Column("studio_id", sa.String(length=36), nullable=True))
    op.create_index("ix_reports_studio_id", "reports", ["studio_id"])
    op.create_foreign_key(
        "fk_reports_studio_id_studios",
        "reports",
        "studios",
        ["studio_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_reports_studio_id_studios", "reports", type_="foreignkey")
    op.drop_index("ix_reports_studio_id", table_name="reports")
    op.drop_column("reports", "studio_id")

    op.drop_index("ix_studio_artifact_studio", table_name="studio_artifacts")
    op.drop_index("ix_studio_artifacts_studio_id", table_name="studio_artifacts")
    op.drop_index("ix_studio_artifacts_id", table_name="studio_artifacts")
    op.drop_table("studio_artifacts")

    op.drop_index("ix_studio_skill_studio", table_name="studio_skills")
    op.drop_index("ix_studio_skills_skill_id", table_name="studio_skills")
    op.drop_index("ix_studio_skills_studio_id", table_name="studio_skills")
    op.drop_index("ix_studio_skills_id", table_name="studio_skills")
    op.drop_table("studio_skills")

    op.drop_index("ix_studio_member_studio", table_name="studio_members")
    op.drop_index("ix_studio_members_user_id", table_name="studio_members")
    op.drop_index("ix_studio_members_studio_id", table_name="studio_members")
    op.drop_index("ix_studio_members_id", table_name="studio_members")
    op.drop_table("studio_members")

    op.drop_index("ix_studio_ds_studio", table_name="studio_data_sources")
    op.drop_index("ix_studio_data_sources_agent_id", table_name="studio_data_sources")
    op.drop_index("ix_studio_data_sources_studio_id", table_name="studio_data_sources")
    op.drop_index("ix_studio_data_sources_id", table_name="studio_data_sources")
    op.drop_table("studio_data_sources")

    op.drop_index("ix_studio_org_owner", table_name="studios")
    op.drop_index("ix_studios_share_token", table_name="studios")
    op.drop_index("ix_studios_organization_id", table_name="studios")
    op.drop_index("ix_studios_owner_user_id", table_name="studios")
    op.drop_index("ix_studios_name", table_name="studios")
    op.drop_index("ix_studios_id", table_name="studios")
    op.drop_table("studios")
