"""agent memory: agent_memories table + FTS index

Revision ID: agentmem1
Revises: at1autotrain
Create Date: 2026-06-21

Agent-authored memory (MemGPT page-in/out). Additive, flag-gated at runtime
(HYBRID_AGENT_MEMORY). Postgres-only GIN full-text index is dialect-guarded so
SQLite dev still migrates.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "agentmem1"
down_revision: Union[str, None] = "at1autotrain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=20), server_default="personal", nullable=False),
        sa.Column("mem_key", sa.String(length=200), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="approved", nullable=False),
        sa.Column("source", sa.String(length=50), server_default="agent", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_memories_id", "agent_memories", ["id"])
    op.create_index("ix_agent_memories_org", "agent_memories", ["organization_id"])
    op.create_index("ix_agent_memories_org_user", "agent_memories", ["organization_id", "user_id"])
    op.create_index("ix_agent_memories_org_ds", "agent_memories", ["organization_id", "data_source_id"])
    op.create_index("ix_agent_memories_status", "agent_memories", ["status"])

    # Postgres-only GIN full-text index on the memory text (dialect-guarded).
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_agent_memories_tsv "
            "ON agent_memories USING gin (to_tsvector('english', text))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_agent_memories_tsv")
    op.drop_table("agent_memories")
