"""connector_sync_run: live per-clone sync log

Revision ID: connsyncrun1
Revises: peruser_tmpl1
Create Date: 2026-07-02

DB-backed, cross-worker-safe live sync log for per-user connector clone builds.
One row per clone (data_source_id UNIQUE, upserted) so the frontend can poll a
CLI-style terminal of the sync regardless of which uvicorn worker served it.
See services/connector_sync.py + services/per_user_connector.py::sync_clone_bg.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "connsyncrun1"
down_revision: Union[str, None] = "peruser_tmpl1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connector_sync_run",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("phase", sa.String(), nullable=False, server_default="connecting"),
        sa.Column("tables_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tables_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("log", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data_source_id", name="uq_connector_sync_run_data_source"),
    )
    op.create_index(
        "ix_connector_sync_run_data_source_id",
        "connector_sync_run",
        ["data_source_id"],
        unique=False,
    )
    op.create_index(
        "ix_connector_sync_run_organization_id",
        "connector_sync_run",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_connector_sync_run_id",
        "connector_sync_run",
        ["id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_connector_sync_run_id", table_name="connector_sync_run")
    op.drop_index("ix_connector_sync_run_organization_id", table_name="connector_sync_run")
    op.drop_index("ix_connector_sync_run_data_source_id", table_name="connector_sync_run")
    op.drop_table("connector_sync_run")
