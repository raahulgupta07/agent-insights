"""add image_url to users (uploaded avatar)

Revision ID: useravatar1
Revises: promptext1
Create Date: 2026-07-04 00:00:00.000000

Adds a single NULLABLE `image_url` column to the `users` table. NULL means the
user has no uploaded avatar and the UI renders the initial-letter placeholder;
a non-NULL value is the public serve path of the uploaded 256x256 PNG.

Idempotent: the column is added only if it is not already present (guarded by an
inspector existence check), mirroring the fork's other repair-style migrations,
so a table that already has the column (e.g. from a partial apply) won't raise.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'useravatar1'
down_revision: Union[str, None] = 'promptext1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'users' not in set(inspector.get_table_names()):
        return
    existing = {c['name'] for c in inspector.get_columns('users')}
    if 'image_url' not in existing:
        op.add_column('users', sa.Column('image_url', sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'users' not in set(inspector.get_table_names()):
        return
    existing = {c['name'] for c in inspector.get_columns('users')}
    # SQLite can't DROP COLUMN pre-3.35; guard PG (the deployed dialect) explicitly.
    if 'image_url' in existing and bind.dialect.name == "postgresql":
        op.drop_column('users', 'image_url')
