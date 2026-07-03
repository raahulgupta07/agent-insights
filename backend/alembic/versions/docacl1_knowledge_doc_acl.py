"""knowledge_docs: optional per-document ACL (allowed_user_ids)

Revision ID: docacl1
Revises: wf2save1
Create Date: 2026-07-03

Phase4-F3 (HYBRID_DOC_ACL). Adds a nullable ``allowed_user_ids`` JSON column to
``knowledge_docs``: a list of user-id strings allowed to see the doc in
institutional grounding. NULL / empty list = visible org-wide (unchanged
org+approved behavior); a non-empty list restricts the doc to those viewers.

Additive, nullable, no default — a fresh column is NULL on every existing row so
retrieval is byte-identical until the flag is on AND a doc carries an allow-list.
PG-guarded; idempotent (ADD COLUMN IF NOT EXISTS).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa  # noqa: F401 (kept for parity with sibling migrations)

revision: str = "docacl1"
down_revision: Union[str, None] = "wf2save1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # PG-only feature path; SQLite test DBs skip

    op.execute(
        "ALTER TABLE knowledge_docs "
        "ADD COLUMN IF NOT EXISTS allowed_user_ids JSON"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE knowledge_docs DROP COLUMN IF EXISTS allowed_user_ids")
