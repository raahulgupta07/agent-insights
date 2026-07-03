"""agent_knowledge: singularized cross-user learning store (Shared Memory)

Revision ID: agentknow1
Revises: colprofile1
Create Date: 2026-07-03

Shared Memory (HYBRID_SHARED_MEMORY), Phase 0. One canonical, sanitized,
scoped row per learned fact. scope_kind+scope_key isolate sharing:
'model'=Power BI dataset_id, 'schema'=DB schema signature, 'file'=file
signature, 'user'=private (user_id). Singularize on
(organization_id, scope_kind, scope_key, kind, source_hash).

No FK constraints by design (enrichment/tracking table — avoids
delete-cascade coupling, same convention as column_profiles). PG-guarded;
idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "agentknow1"
down_revision: Union[str, None] = "colprofile1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # PG-only feature path; SQLite test DBs skip

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_knowledge (
            id                  VARCHAR(36) PRIMARY KEY,
            organization_id     VARCHAR(36) NOT NULL,
            scope_kind          VARCHAR(20) NOT NULL DEFAULT 'model',
            scope_key           VARCHAR(200) NOT NULL,
            kind                VARCHAR(20) NOT NULL,
            title               VARCHAR(300),
            content_json        JSON,
            text                TEXT,
            source_hash         VARCHAR(64) NOT NULL,
            verified_count      INTEGER NOT NULL DEFAULT 1,
            created_by_user_id  VARCHAR(36),
            data_source_id      VARCHAR(36),
            status              VARCHAR(16) NOT NULL DEFAULT 'pending',
            created_at          TIMESTAMP,
            updated_at          TIMESTAMP,
            deleted_at          TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_knowledge_singular
        ON agent_knowledge (organization_id, scope_kind, scope_key, kind, source_hash)
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_knowledge_org ON agent_knowledge (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_knowledge_scope ON agent_knowledge (organization_id, scope_kind, scope_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_knowledge_status ON agent_knowledge (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_knowledge_user ON agent_knowledge (organization_id, created_by_user_id)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS agent_knowledge")
