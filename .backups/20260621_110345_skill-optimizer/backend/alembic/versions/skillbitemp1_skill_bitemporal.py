"""bi-temporal columns on skills: valid_at / invalid_at / superseded_by

Revision ID: skillbitemp1
Revises: bitemp2
Create Date: 2026-06-21

Gives the Skill doc a fact timeline so the Skill Optimizer (upgrade #7) can write
a NEW version and supersede the old one instead of overwriting in place. Additive
+ nullable -> existing rows are all "current" (invalid_at IS NULL). Flag-gated at
runtime (HYBRID_SKILL_OPTIMIZE); reads only filter on these when the flag is on,
so OFF == prior behavior. Works on PG + SQLite.

Unlike bitemp2 (metric_definitions / semantic_tables), `skills` currently has NO
unique constraint to drop -> we just ADD a partial unique index that constrains
only the CURRENT ACTIVE row per logical key (organization_id, scope, name). The
optimizer's new version lands status='pending' (not 'active'), so it can coexist
with the live active row; on accept the prior active row is superseded
(invalid_at set) before/as the new one flips to active.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "skillbitemp1"
down_revision: Union[str, None] = "bitemp2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("valid_at", sa.DateTime(), nullable=True))
    op.add_column("skills", sa.Column("invalid_at", sa.DateTime(), nullable=True))
    op.add_column("skills", sa.Column("superseded_by", sa.String(length=36), nullable=True))

    # Only ONE currently-valid ACTIVE row per logical key. Scoped to
    # status='active' (not just invalid_at IS NULL) so that draft/pending/
    # archived versions — which also carry invalid_at IS NULL — can coexist
    # alongside the live active version (the optimizer writes a pending new
    # version while an active one already exists). Postgres-only DDL (partial
    # index); SQLite dev/CI skips (PG-only prod path).
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "uq_skill_current",
            "skills",
            ["organization_id", "scope", "name"],
            unique=True,
            postgresql_where=sa.text("invalid_at IS NULL AND status = 'active'"),
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("uq_skill_current", table_name="skills")
    op.drop_column("skills", "superseded_by")
    op.drop_column("skills", "invalid_at")
    op.drop_column("skills", "valid_at")
