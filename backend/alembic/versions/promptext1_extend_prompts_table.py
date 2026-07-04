"""extend prompts table with completion-shaped columns

Revision ID: promptext1
Revises: costattr1
Create Date: 2026-07-04 00:00:00.000000

Adds the completion-shaped execution spec (mode/model_id/mentions/parameters)
and scope/classification (scope/is_starter) columns to the `prompts` table so a
saved prompt can carry how it should run and where it is visible.

All new columns are NULLABLE — rows written before this migration survive with
NULLs (the app treats NULL mode as 'chat' and NULL scope as 'agent' via the model
defaults on new writes). Idempotent: each column is added only if it is not
already present, mirroring the fork's other repair-style migrations, so a table
that already has a column (e.g. from a partial apply) won't raise.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'promptext1'
down_revision: Union[str, None] = 'costattr1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, type) — all added NULLABLE, no server_default (existing rows stay NULL).
NEW_COLUMNS = [
    ('mode', sa.String()),
    ('model_id', sa.String(length=36)),
    ('mentions', sa.JSON()),
    ('parameters', sa.JSON()),
    ('scope', sa.String()),
    ('is_starter', sa.Boolean()),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'prompts' not in set(inspector.get_table_names()):
        return
    existing = {c['name'] for c in inspector.get_columns('prompts')}
    for name, coltype in NEW_COLUMNS:
        if name not in existing:
            op.add_column('prompts', sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'prompts' not in set(inspector.get_table_names()):
        return
    existing = {c['name'] for c in inspector.get_columns('prompts')}
    # SQLite can't DROP COLUMN pre-3.35; guard PG (the deployed dialect) explicitly.
    is_pg = bind.dialect.name == "postgresql"
    for name, _ in reversed(NEW_COLUMNS):
        if name in existing and is_pg:
            op.drop_column('prompts', name)
