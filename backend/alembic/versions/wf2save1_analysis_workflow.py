"""analysis_workflows: saved reusable parameterized analyses (Workflows v2)

Revision ID: wf2save1
Revises: agentknow1
Create Date: 2026-07-03

Workflows v2 (HYBRID_WORKFLOWS_V2). One row per saved analysis: the captured
step plan (ordered analysis prompts) + a params schema derived from the
{placeholder} tokens in those prompts. scope=private|org. Replayed headless so
the analysis runs consistently for every user.

No FK constraints by design (additive feature table — avoids delete-cascade
coupling, same convention as agent_knowledge). PG-guarded; idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa  # noqa: F401 (kept for parity with sibling migrations)

revision: str = "wf2save1"
down_revision: Union[str, None] = "agentknow1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # PG-only feature path; SQLite test DBs skip

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_workflows (
            id                  VARCHAR(36) PRIMARY KEY,
            organization_id     VARCHAR(36) NOT NULL,
            owner_user_id       VARCHAR(36),
            name                VARCHAR(300) NOT NULL,
            description         TEXT,
            steps_json          JSON,
            params_schema_json  JSON,
            scope               VARCHAR(16) NOT NULL DEFAULT 'private',
            run_count           INTEGER NOT NULL DEFAULT 0,
            status              VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at          TIMESTAMP,
            updated_at          TIMESTAMP,
            deleted_at          TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analysis_workflows_org "
        "ON analysis_workflows (organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analysis_workflows_owner "
        "ON analysis_workflows (organization_id, owner_user_id)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS analysis_workflows")
