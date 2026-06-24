"""studio_bound_packs: Domain Packs (lightweight skills engine)

Revision ID: studiopack1
Revises: dashversions1
Create Date: 2026-06-24

New table backing the Domain Packs subsystem — the lightweight, data-gated
alternative to the native heavy Skills engine. Each row binds one declarative
pack (method file in app/ai/packs/library) to one studio: the per-agent
binding map (logical input -> real column) for that pack's invariant method,
plus a status used by the router's hard candidate gate.

Additive + fully gated by flags.DOMAIN_PACKS (default OFF) — nothing reads this
table unless the flag is on, so the table is inert on existing deploys.
Dialect-safe (PG + SQLite). down_revision chains off the single true head
`dashversions1`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "studiopack1"
down_revision: Union[str, None] = "dashversions1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_bound_packs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("pack_id", sa.String(length=120), nullable=False),
        sa.Column("binding_map", sa.JSON(), nullable=True),
        sa.Column("output_spec", sa.JSON(), nullable=True),
        sa.Column("eval_goldens", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="pack"),
        sa.Column("conf", sa.Float(), nullable=True),
        sa.Column("missing", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_bound_pack_studio", "studio_bound_packs",
                    ["studio_id", "status"], unique=False)
    op.create_index("ix_studio_bound_pack_pack", "studio_bound_packs",
                    ["studio_id", "pack_id"], unique=False)
    op.create_index(op.f("ix_studio_bound_packs_id"), "studio_bound_packs",
                    ["id"], unique=True)
    op.create_index(op.f("ix_studio_bound_packs_studio_id"), "studio_bound_packs",
                    ["studio_id"], unique=False)
    op.create_index(op.f("ix_studio_bound_packs_pack_id"), "studio_bound_packs",
                    ["pack_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_studio_bound_packs_pack_id"), table_name="studio_bound_packs")
    op.drop_index(op.f("ix_studio_bound_packs_studio_id"), table_name="studio_bound_packs")
    op.drop_index(op.f("ix_studio_bound_packs_id"), table_name="studio_bound_packs")
    op.drop_index("ix_studio_bound_pack_pack", table_name="studio_bound_packs")
    op.drop_index("ix_studio_bound_pack_studio", table_name="studio_bound_packs")
    op.drop_table("studio_bound_packs")
