"""add monthly USD spend limit to usage_policies (#488)

Revision ID: usdquota1
Revises: svcacct1
Create Date: 2026-07-04 00:00:00.000000

Adds ``monthly_spend_limit_usd`` (Numeric(18, 6), nullable) to ``usage_policies``
for the per-org / per-user monthly USD spend cap. The cap is enforced against
``llm_usage_records.total_cost_usd`` at LLM-call time, but ONLY when the
``HYBRID_USD_QUOTA`` flag is ON. The column itself is additive/unconditional:
NULL = unlimited spend, so an unset column is a no-op even with the flag on.

Idempotent inspector-guarded add-column (mirrors the fork's other repair-style
migrations) so a re-run / already-patched DB is safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'usdquota1'
down_revision: Union[str, None] = 'svcacct1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table: str, column: str) -> bool:
    try:
        return column in {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "usage_policies", "monthly_spend_limit_usd"):
        op.add_column(
            "usage_policies",
            sa.Column("monthly_spend_limit_usd", sa.Numeric(18, 6), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, "usage_policies", "monthly_spend_limit_usd"):
        op.drop_column("usage_policies", "monthly_spend_limit_usd")
