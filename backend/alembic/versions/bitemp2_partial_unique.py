"""bi-temporal partial unique: only ONE CURRENT row per logical key

Revision ID: bitemp2
Revises: bitemp1
Create Date: 2026-06-21

Bi-temporal versioning needs MULTIPLE versions of the same logical fact
(metric_definitions / semantic_tables) to coexist — the prior versions are
invalidated (invalid_at set) when a new one is approved. The old plain UNIQUE
on (organization_id, data_source_id, name/table_name) forbids that, so we swap
it for a PARTIAL unique index that only constrains the CURRENT row
(WHERE invalid_at IS NULL). Postgres-only DDL (partial indexes); SQLite dev
just skips (it can't easily drop a named constraint and the dev path uses PG).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "bitemp2"
down_revision: Union[str, None] = "bitemp1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (dev/CI) can't drop a named constraint without table rebuild and
        # doesn't need the partial unique for the PG-only prod path. No-op.
        return
    # Drop the old "one row per key" uniques (may already be gone -> IF EXISTS).
    op.execute(
        "ALTER TABLE metric_definitions "
        "DROP CONSTRAINT IF EXISTS uq_metric_definition_org_ds_name"
    )
    op.execute(
        "ALTER TABLE semantic_tables "
        "DROP CONSTRAINT IF EXISTS uq_semantic_table_org_ds_name"
    )
    # Only ONE currently-valid APPROVED row per logical key. Scoped to
    # status='approved' (not just invalid_at IS NULL) so that pending/draft/
    # rejected proposals — which also carry invalid_at IS NULL — can still
    # coexist alongside an approved version (the existing review workflow:
    # AI-suggest / proposer / manual create a pending row while an approved one
    # already exists). A proposal is not "the current fact" until approved;
    # bi-temporal currency therefore applies to approved rows. On approve, the
    # prior approved row is superseded (invalid_at set) before/as the new one
    # goes live, so the invariant "one approved current row per key" holds.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_metric_def_current "
        "ON metric_definitions (organization_id, data_source_id, name) "
        "WHERE invalid_at IS NULL AND status = 'approved'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_semantic_current "
        "ON semantic_tables (organization_id, data_source_id, table_name) "
        "WHERE invalid_at IS NULL AND status = 'approved'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS uq_metric_def_current")
    op.execute("DROP INDEX IF EXISTS uq_semantic_current")
    # Best-effort restore of the original plain uniques.
    op.execute(
        "ALTER TABLE metric_definitions "
        "ADD CONSTRAINT uq_metric_definition_org_ds_name "
        "UNIQUE (organization_id, data_source_id, name)"
    )
    op.execute(
        "ALTER TABLE semantic_tables "
        "ADD CONSTRAINT uq_semantic_table_org_ds_name "
        "UNIQUE (organization_id, data_source_id, table_name)"
    )
