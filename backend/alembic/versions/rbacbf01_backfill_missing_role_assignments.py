"""rbac backfill: re-seed missing system roles + backfill admin role_assignments

Revision ID: rbacbf01
Revises: docacl1
Create Date: 2026-07-04 00:00:00.000000

Upstream bagofwords #529 port. The two GLOBAL system roles (`admin` / `member`,
`is_system=True`, `organization_id IS NULL`) were only ever seeded in the
`e6f7g8h9i0j1_rbac_mvp` migration via `op.bulk_insert`. A full DB TRUNCATE wiped
them, and `OrganizationService._assign_system_role` silently early-returns when the
system role is absent, so a freshly registered admin ends up with NO
role_assignment -> no permissions -> 403 on onboarding.

This migration is idempotent and self-healing:
  1. Re-seed the `admin` / `member` system roles ONLY if absent.
  2. Backfill a missing admin `role_assignments` row for every org membership whose
     user is an org admin (memberships.role = 'admin') but has no assignment yet.

Postgres-only DDL/functions (`gen_random_uuid()`) are guarded on the dialect.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'rbacbf01'
down_revision: Union[str, Sequence[str], None] = 'docacl1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirrors permissions_registry / the rbac_mvp seed.
_ADMIN_PERMISSIONS = '["full_admin_access"]'
_MEMBER_PERMISSIONS = (
    '["view_reports", "create_reports", "update_reports", "delete_reports", '
    '"publish_reports", "manage_files", "view_members"]'
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # RBAC backfill is only meaningful on the production Postgres deployment;
        # SQLite (tests) has no gen_random_uuid() and never hit the TRUNCATE bug.
        return

    # --- 1. Idempotently re-seed the two global system roles ------------------
    # Guard on (name, is_system, organization_id IS NULL); insert only if absent.
    for name, description, permissions in (
        ('admin', 'Full administrator access', _ADMIN_PERMISSIONS),
        ('member', 'Standard member access', _MEMBER_PERMISSIONS),
    ):
        bind.execute(
            sa.text(
                """
                INSERT INTO roles
                    (id, created_at, updated_at, organization_id,
                     name, description, permissions, is_system)
                SELECT gen_random_uuid()::text, now(), now(), NULL,
                       :name, :description, CAST(:permissions AS json), true
                WHERE NOT EXISTS (
                    SELECT 1 FROM roles
                    WHERE name = :name
                      AND is_system = true
                      AND organization_id IS NULL
                )
                """
            ),
            {"name": name, "description": description, "permissions": permissions},
        )

    # --- 2. Backfill missing admin role_assignments ---------------------------
    # For every non-deleted membership whose user is an org admin but has no
    # matching admin role_assignment, create one. Uses the system admin role.
    bind.execute(
        sa.text(
            """
            INSERT INTO role_assignments
                (id, created_at, updated_at, organization_id,
                 role_id, principal_type, principal_id)
            SELECT gen_random_uuid()::text, now(), now(),
                   m.organization_id, r.id, 'user', m.user_id
            FROM memberships m
            CROSS JOIN (
                SELECT id FROM roles
                WHERE name = 'admin'
                  AND is_system = true
                  AND organization_id IS NULL
                LIMIT 1
            ) r
            WHERE m.role = 'admin'
              AND m.user_id IS NOT NULL
              AND m.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM role_assignments ra
                  WHERE ra.organization_id = m.organization_id
                    AND ra.role_id = r.id
                    AND ra.principal_type = 'user'
                    AND ra.principal_id = m.user_id
              )
            """
        )
    )


def downgrade() -> None:
    # No-op: re-seeding system roles and backfilling assignments is a data heal.
    # Dropping them would re-introduce the 403 bug this migration fixes.
    pass
