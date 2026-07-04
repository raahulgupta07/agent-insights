"""create file_references table (#497)

Revision ID: fileref1
Revises: usdquota1
Create Date: 2026-07-04 00:00:00.000000

Adds ``file_references`` — a durable org-scoped link {report} -> {uploaded File}
so a user can pin an uploaded file into a report's prompt context and have its
text injected into the agent context. Read path is gated behind
``HYBRID_FILE_REFERENCES`` (default OFF) — the table is additive and inert until
the flag is on.

Idempotent: guarded by a table-existence check so a re-run / already-patched DB
is safe (mirrors the fork's other repair-style migrations).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fileref1'
down_revision: Union[str, None] = 'usdquota1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, table: str) -> bool:
    try:
        return inspector.has_table(table)
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "file_references"):
        return
    op.create_table(
        "file_references",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("report_id", sa.String(length=36), sa.ForeignKey("reports.id"), nullable=False, index=True),
        sa.Column("file_id", sa.String(length=36), sa.ForeignKey("files.id"), nullable=False, index=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "file_references"):
        op.drop_table("file_references")
