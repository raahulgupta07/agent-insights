"""Studio Context Harness ST7/ST8: studio_instructions + studio_examples
tables, plus studios.bootstrap_state column.

Auto-born per-studio rules + golden examples for the context assembler. Both
new tables are ALL NEW; rules/examples are born `pending` and only reach the
agent once a human flips them to `active` (reuses the existing review gate).
studios.bootstrap_state (JSON) records which auto-born steps have run. All
Studio Context Harness behavior is gated by flags.HYBRID_STUDIOS and defaults
OFF.

Dialect-agnostic (plain tables — works on SQLite + Postgres, no schema qualifier).

Revision ID: studio2harness1
Revises: studio1base1
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "studio2harness1"
down_revision: Union[str, None] = "studio1base1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- studio_instructions ----------------------------------------------
    op.create_table(
        "studio_instructions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="auto"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("instruction_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"]),
        sa.ForeignKeyConstraint(["instruction_id"], ["instructions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_instructions_id", "studio_instructions", ["id"])
    op.create_index("ix_studio_instructions_studio_id", "studio_instructions", ["studio_id"])
    op.create_index("ix_studio_instructions_instruction_id", "studio_instructions", ["instruction_id"])
    op.create_index("ix_studio_instruction_studio", "studio_instructions", ["studio_id", "status"])

    # --- studio_examples ---------------------------------------------------
    op.create_table(
        "studio_examples",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="auto"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_examples_id", "studio_examples", ["id"])
    op.create_index("ix_studio_examples_studio_id", "studio_examples", ["studio_id"])
    op.create_index("ix_studio_example_studio", "studio_examples", ["studio_id", "status"])

    # --- studios.bootstrap_state ------------------------------------------
    op.add_column("studios", sa.Column("bootstrap_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("studios", "bootstrap_state")

    op.drop_index("ix_studio_example_studio", table_name="studio_examples")
    op.drop_index("ix_studio_examples_studio_id", table_name="studio_examples")
    op.drop_index("ix_studio_examples_id", table_name="studio_examples")
    op.drop_table("studio_examples")

    op.drop_index("ix_studio_instruction_studio", table_name="studio_instructions")
    op.drop_index("ix_studio_instructions_instruction_id", table_name="studio_instructions")
    op.drop_index("ix_studio_instructions_studio_id", table_name="studio_instructions")
    op.drop_index("ix_studio_instructions_id", table_name="studio_instructions")
    op.drop_table("studio_instructions")
