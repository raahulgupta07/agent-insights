"""Phase 6: table_edges (approval-gated learned join / lineage graph).

New table holding one join relationship per row
(left_table.left_col <-> right_table.right_col) with a join_count, confidence
and provenance (inferred|declared). Approval-gated: mined edges land
status='pending' and only status='approved' rows reach the agent. Additive;
gated at runtime, default behavior unchanged until consumed.

Revision ID: joingraph1
Revises: kepler2cb1
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "joingraph1"
down_revision: Union[str, None] = "kepler2cb1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "table_edges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("left_table", sa.String(), nullable=False),
        sa.Column("left_col", sa.String(), nullable=False),
        sa.Column("right_table", sa.String(), nullable=False),
        sa.Column("right_col", sa.String(), nullable=False),
        sa.Column("join_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="inferred"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("structured_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "data_source_id",
            "left_table", "left_col", "right_table", "right_col",
            name="uq_table_edge_org_ds_cols",
        ),
    )
    op.create_index("ix_table_edges_organization_id", "table_edges", ["organization_id"])
    op.create_index("ix_table_edges_data_source_id", "table_edges", ["data_source_id"])
    op.create_index("ix_table_edges_left_table", "table_edges", ["left_table"])
    op.create_index("ix_table_edges_right_table", "table_edges", ["right_table"])
    op.create_index("ix_table_edges_status", "table_edges", ["status"])


def downgrade() -> None:
    op.drop_index("ix_table_edges_status", table_name="table_edges")
    op.drop_index("ix_table_edges_right_table", table_name="table_edges")
    op.drop_index("ix_table_edges_left_table", table_name="table_edges")
    op.drop_index("ix_table_edges_data_source_id", table_name="table_edges")
    op.drop_index("ix_table_edges_organization_id", table_name="table_edges")
    op.drop_table("table_edges")
