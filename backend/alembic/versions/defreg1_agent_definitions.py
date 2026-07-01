"""agent_definitions: Definition Registry (Pipeline v1 P3)

Revision ID: defreg1
Revises: sessumm1
Create Date: 2026-06-29

Single source of truth for business definitions (metric / filter / rule) with
the SQL predicate that implements each + the expected ground-truth answer.
Goldens/instructions reference a definition so one correction propagates.

Additive, idempotent (IF NOT EXISTS). PG-guarded.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "defreg1"
down_revision: Union[str, None] = "sessumm1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_definitions (
            id              varchar(36) PRIMARY KEY,
            organization_id varchar(36) NOT NULL,
            data_source_id  varchar(36),
            studio_id       varchar(36),
            name            varchar NOT NULL,
            kind            varchar(20) NOT NULL DEFAULT 'metric',
            sql_predicate   text NOT NULL DEFAULT '',
            filters         json NOT NULL DEFAULT '[]'::json,
            columns_used    json NOT NULL DEFAULT '[]'::json,
            expected        json NOT NULL DEFAULT '[]'::json,
            description     text NOT NULL DEFAULT '',
            logic_text      text NOT NULL DEFAULT '',
            source_doc      varchar,
            status          varchar(20) NOT NULL DEFAULT 'pending',
            created_at      timestamp DEFAULT now(),
            updated_at      timestamp DEFAULT now(),
            deleted_at      timestamp
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_def_org_ds "
        "ON agent_definitions (organization_id, data_source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_def_name "
        "ON agent_definitions (organization_id, name)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS agent_definitions")
