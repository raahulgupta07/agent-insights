"""Phase 5: knowledge_docs + knowledge_doc_chunks (approval-gated docs RAG).

Two new tables: ``knowledge_docs`` (one row per ingested business document,
status-gated) and ``knowledge_doc_chunks`` (chunked retrievable text). Retrieval
is Postgres full-text search (vectorless) — a GIN functional index on
``to_tsvector('english', text)`` backs the docs context builder. Only chunks of
an ``approved`` parent doc surface to the agent. Additive; gated at runtime
(``HYBRID_DOC_KNOWLEDGE``), default behavior unchanged until consumed.

The FTS GIN index is Postgres-only (guarded on dialect) so SQLite dev/test
still migrates cleanly.

Revision ID: docknow1
Revises: joingraph1
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "docknow1"
down_revision: Union[str, None] = "joingraph1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_docs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="upload"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("structured_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "data_source_id", "content_hash",
            name="uq_knowledge_doc_org_ds_hash",
        ),
    )
    op.create_index("ix_knowledge_docs_organization_id", "knowledge_docs", ["organization_id"])
    op.create_index("ix_knowledge_docs_data_source_id", "knowledge_docs", ["data_source_id"])
    op.create_index("ix_knowledge_docs_content_hash", "knowledge_docs", ["content_hash"])
    op.create_index("ix_knowledge_docs_status", "knowledge_docs", ["status"])

    op.create_table(
        "knowledge_doc_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("doc_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["doc_id"], ["knowledge_docs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_doc_chunks_organization_id", "knowledge_doc_chunks", ["organization_id"])
    op.create_index("ix_knowledge_doc_chunks_doc_id", "knowledge_doc_chunks", ["doc_id"])

    # Postgres-only GIN full-text index backing the docs context builder.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_knowledge_doc_chunks_fts ON knowledge_doc_chunks "
            "USING gin (to_tsvector('english', text))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_doc_chunks_fts")
    op.drop_index("ix_knowledge_doc_chunks_doc_id", table_name="knowledge_doc_chunks")
    op.drop_index("ix_knowledge_doc_chunks_organization_id", table_name="knowledge_doc_chunks")
    op.drop_table("knowledge_doc_chunks")
    op.drop_index("ix_knowledge_docs_status", table_name="knowledge_docs")
    op.drop_index("ix_knowledge_docs_content_hash", table_name="knowledge_docs")
    op.drop_index("ix_knowledge_docs_data_source_id", table_name="knowledge_docs")
    op.drop_index("ix_knowledge_docs_organization_id", table_name="knowledge_docs")
    op.drop_table("knowledge_docs")
