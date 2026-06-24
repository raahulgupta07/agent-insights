"""autotrain foundation: ingest_batches, schema_contracts, upload_caches

Revision ID: at1autotrain
Revises: skillrun1
Create Date: 2026-06-20

Adds the three tracking tables for the autotrain ingest pipeline. Additive,
flag-gated at runtime (HYBRID_AUTOTRAIN). Works on Postgres + SQLite (no
schema-qualified / Postgres-only DDL here).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "at1autotrain"
down_revision: Union[str, None] = "skillrun1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_cols() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "ingest_batches",
        *_base_cols(),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("file_id", sa.String(length=36), nullable=True),
        sa.Column("file_hash", sa.String(), nullable=True),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("logical_dataset", sa.String(), nullable=True),
        sa.Column("target_table", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="staged", nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quarantine_reason", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingest_batches_id", "ingest_batches", ["id"])
    op.create_index("ix_ingest_batches_org", "ingest_batches", ["organization_id"])
    op.create_index("ix_ingest_batches_hash", "ingest_batches", ["file_hash"])
    op.create_index("ix_ingest_batches_org_ds", "ingest_batches", ["organization_id", "data_source_id"])

    op.create_table(
        "schema_contracts",
        *_base_cols(),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("logical_dataset", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("columns", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schema_contracts_id", "schema_contracts", ["id"])
    op.create_index("ix_schema_contracts_org", "schema_contracts", ["organization_id"])
    op.create_index(
        "ix_schema_contracts_org_ds_logical",
        "schema_contracts",
        ["organization_id", "data_source_id", "logical_dataset"],
    )

    op.create_table(
        "upload_caches",
        *_base_cols(),
        sa.Column("file_hash", sa.String(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("file_ext", sa.String(), nullable=True),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("rescue_used", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_caches_id", "upload_caches", ["id"])
    op.create_index("ix_upload_caches_hash", "upload_caches", ["file_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("upload_caches")
    op.drop_table("schema_contracts")
    op.drop_table("ingest_batches")
