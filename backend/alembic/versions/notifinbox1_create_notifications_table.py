"""create notifications table (in-app notification inbox)

Revision ID: notifinbox1
Revises: useravatar1
Create Date: 2026-07-04 00:00:00.000000

Greenfield in-app inbox table (bell + dropdown). UNRELATED to the outbound-email
`notification_service` — this stores per-recipient inbox rows with read/dismiss
state. ``user_id`` NULL = org-wide notification.

Idempotent: the table is created only if it is not already present (guarded by an
inspector existence check), mirroring the fork's other repair-style migrations.
PG-guarded DDL where dialect-specific.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'notifinbox1'
down_revision: Union[str, None] = 'useravatar1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'notifications' in set(inspector.get_table_names()):
        return

    op.create_table(
        'notifications',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('actor_user_id', sa.String(length=36), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default='system'),
        sa.Column('type', sa.String(), nullable=False, server_default='generic'),
        sa.Column('severity', sa.String(), nullable=False, server_default='info'),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('link', sa.String(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('is_dismissed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
    )
    op.create_index(
        'ix_notifications_org_user_read', 'notifications',
        ['organization_id', 'user_id', 'is_read'],
    )
    op.create_index(
        'ix_notifications_created_at', 'notifications', ['created_at'],
    )
    op.create_index(
        'ix_notifications_organization_id', 'notifications', ['organization_id'],
    )
    op.create_index(
        'ix_notifications_user_id', 'notifications', ['user_id'],
    )
    op.create_index(
        'ix_notifications_source', 'notifications', ['source'],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'notifications' not in set(inspector.get_table_names()):
        return
    op.drop_table('notifications')
