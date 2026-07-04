"""create service_accounts table + extend api_keys for service-account keys

Revision ID: svcacct1
Revises: notifinbox1
Create Date: 2026-07-04 00:00:00.000000

Greenfield Service Accounts: machine/service principals an org admin creates,
each able to hold one or more API keys (``bow_`` prefix, SHA-256 hashed) used
for headless / programmatic access.

The keys reuse the existing ``api_keys`` table (same generator + hashing as
MCP / sync ``bow_`` keys) rather than a parallel table. This migration:
  * creates ``service_accounts`` (org-owned metadata), and
  * extends ``api_keys`` with ``service_account_id`` (which account owns the
    key) + ``revoked_at`` (a revoked key must never authenticate), and relaxes
    ``user_id`` to nullable (service-account keys have no backing user row).

Idempotent + PG-guarded, mirroring the fork's other repair-style migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'svcacct1'
down_revision: Union[str, None] = 'notifinbox1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'service_accounts' not in tables:
        op.create_table(
            'service_accounts',
            sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('created_by_user_id', sa.String(length=36), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        )
        op.create_index(
            'ix_service_accounts_organization_id', 'service_accounts', ['organization_id'],
        )

    if 'api_keys' in tables:
        cols = {c['name'] for c in inspector.get_columns('api_keys')}
        if 'service_account_id' not in cols:
            op.add_column('api_keys', sa.Column('service_account_id', sa.String(length=36), nullable=True))
            op.create_index('ix_api_keys_service_account_id', 'api_keys', ['service_account_id'])
            if is_pg:
                op.create_foreign_key(
                    'fk_api_keys_service_account_id', 'api_keys', 'service_accounts',
                    ['service_account_id'], ['id'],
                )
        if 'revoked_at' not in cols:
            op.add_column('api_keys', sa.Column('revoked_at', sa.DateTime(), nullable=True))
        # Service-account keys have no backing user → user_id must be nullable.
        # SQLite can't ALTER a column's nullability in-place; it's created
        # nullable there on a fresh install, so only PG needs the relax.
        if is_pg:
            op.alter_column('api_keys', 'user_id', existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'api_keys' in tables:
        cols = {c['name'] for c in inspector.get_columns('api_keys')}
        if 'revoked_at' in cols:
            op.drop_column('api_keys', 'revoked_at')
        if 'service_account_id' in cols:
            if is_pg:
                try:
                    op.drop_constraint('fk_api_keys_service_account_id', 'api_keys', type_='foreignkey')
                except Exception:
                    pass
            try:
                op.drop_index('ix_api_keys_service_account_id', table_name='api_keys')
            except Exception:
                pass
            op.drop_column('api_keys', 'service_account_id')

    if 'service_accounts' in tables:
        op.drop_table('service_accounts')
