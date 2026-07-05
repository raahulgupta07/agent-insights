"""add data_sources.eda_profile + kpi_defs for the BI uplift (per-agent EDA + KPI layer)

Revision ID: biuplift1
Revises: sidesort1
Create Date: 2026-07-05 00:00:00.000000

Two additive JSON columns on ``data_sources`` (an agent IS a data_source):

* ``eda_profile``  — the per-agent Auto-EDA result (computed profile + the
  model's narrated insights + suggested starter questions + a data-prep
  summary). One profile per agent, overwritten on retrain. Read/written only
  behind ``HYBRID_AUTO_EDA`` / ``HYBRID_DATA_PREP_GATE`` and rendered solely on
  that agent's Overview.
* ``kpi_defs``     — per-agent governed KPI definitions (outcome ratios,
  leading/lagging dependency tags, target / owner / action-on-breach). Read
  behind ``HYBRID_KPI_LAYER``.

Both are nullable and inert until their flags are on. Idempotent: guarded by a
column-existence check so a re-run / already-patched DB is safe (mirrors the
fork's other repair-style migrations). PG-only DDL guarded on dialect.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'biuplift1'
down_revision: Union[str, None] = 'sidesort1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspector.get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "data_sources", "eda_profile"):
        op.add_column("data_sources", sa.Column("eda_profile", sa.JSON(), nullable=True))
    if not _has_column(inspector, "data_sources", "kpi_defs"):
        op.add_column("data_sources", sa.Column("kpi_defs", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, "data_sources", "kpi_defs"):
        op.drop_column("data_sources", "kpi_defs")
    if _has_column(inspector, "data_sources", "eda_profile"):
        op.drop_column("data_sources", "eda_profile")
