"""hybrid Phase 8 prep: enable the pgvector extension (Postgres only)

Creates the ``vector`` extension so later Phase-8 work (entity/correlation
embeddings, cross-encoder rerank candidates, non-text semantic ingest) can add
``vector`` columns + ANN indexes. The DB image is now ``pgvector/pgvector:pg18``
which ships the extension; this migration just turns it on.

Postgres-only and idempotent: guarded on the dialect so SQLite (unit/dev) is a
no-op, and ``IF NOT EXISTS`` so a re-run / an image that pre-creates it is safe.
No tables/columns added yet — those land with the Phase-8 features behind their
flags. Enabling the extension alone changes no app behavior.

Revision ID: v1e2c3t4o5r6
Revises: aac1c2c3c4c5
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v1e2c3t4o5r6"
down_revision: Union[str, None] = "aac1c2c3c4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Only drops the extension; no dependent objects are created here.
        op.execute("DROP EXTENSION IF EXISTS vector")
