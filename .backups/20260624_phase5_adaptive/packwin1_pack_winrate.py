"""pack_winrate / pack_fire_events / org_packs: Domain Packs Phase 5 (adaptive + promote)

Revision ID: packwin1
Revises: studioteach1
Create Date: 2026-06-24

Three additive tables for the adaptive + harden phase of the Domain Packs engine:

  * pack_fire_events  — which pack fired on which completion (the winrate signal
                        link; one row per completion, written at injection time).
  * pack_winrates     — aggregated thumbs feedback per (studio, pack, cluster);
                        the router demotes a pack whose score keeps losing.
  * org_packs         — a studio skill promoted to the whole org (DB-backed,
                        writable extension of the immutable yaml library).

All inert unless flags.DOMAIN_PACKS — nothing reads/writes them on existing
deploys. Dialect-safe (PG + SQLite). down_revision chains off the head
`studioteach1`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "packwin1"
down_revision: Union[str, None] = "studioteach1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pack_fire_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("completion_id", sa.String(length=36), nullable=False),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("pack_id", sa.String(length=120), nullable=False),
        sa.Column("question_cluster", sa.String(length=160), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pack_fire_events_id"), "pack_fire_events", ["id"], unique=True)
    op.create_index(op.f("ix_pack_fire_events_completion_id"), "pack_fire_events",
                    ["completion_id"], unique=False)
    op.create_index(op.f("ix_pack_fire_events_studio_id"), "pack_fire_events",
                    ["studio_id"], unique=False)
    op.create_index(op.f("ix_pack_fire_events_organization_id"), "pack_fire_events",
                    ["organization_id"], unique=False)
    op.create_index("ix_pack_fire_completion", "pack_fire_events",
                    ["completion_id"], unique=False)

    op.create_table(
        "pack_winrates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("studio_id", sa.String(length=36), nullable=False),
        sa.Column("pack_id", sa.String(length=120), nullable=False),
        sa.Column("question_cluster", sa.String(length=160), nullable=False, server_default="default"),
        sa.Column("passes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fails", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pack_winrates_id"), "pack_winrates", ["id"], unique=True)
    op.create_index(op.f("ix_pack_winrates_studio_id"), "pack_winrates",
                    ["studio_id"], unique=False)
    op.create_index(op.f("ix_pack_winrates_pack_id"), "pack_winrates",
                    ["pack_id"], unique=False)
    op.create_index("ix_pack_winrate_lookup", "pack_winrates",
                    ["studio_id", "pack_id", "question_cluster"], unique=False)

    op.create_table(
        "org_packs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("pack_id", sa.String(length=120), nullable=False),
        sa.Column("pack_body", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("source_studio_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_org_packs_id"), "org_packs", ["id"], unique=True)
    op.create_index(op.f("ix_org_packs_organization_id"), "org_packs",
                    ["organization_id"], unique=False)
    op.create_index(op.f("ix_org_packs_pack_id"), "org_packs",
                    ["pack_id"], unique=False)
    op.create_index("ix_org_pack_org", "org_packs",
                    ["organization_id", "status"], unique=False)
    op.create_index("ix_org_pack_lookup", "org_packs",
                    ["organization_id", "pack_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_org_pack_lookup", table_name="org_packs")
    op.drop_index("ix_org_pack_org", table_name="org_packs")
    op.drop_index(op.f("ix_org_packs_pack_id"), table_name="org_packs")
    op.drop_index(op.f("ix_org_packs_organization_id"), table_name="org_packs")
    op.drop_index(op.f("ix_org_packs_id"), table_name="org_packs")
    op.drop_table("org_packs")

    op.drop_index("ix_pack_winrate_lookup", table_name="pack_winrates")
    op.drop_index(op.f("ix_pack_winrates_pack_id"), table_name="pack_winrates")
    op.drop_index(op.f("ix_pack_winrates_studio_id"), table_name="pack_winrates")
    op.drop_index(op.f("ix_pack_winrates_id"), table_name="pack_winrates")
    op.drop_table("pack_winrates")

    op.drop_index("ix_pack_fire_completion", table_name="pack_fire_events")
    op.drop_index(op.f("ix_pack_fire_events_organization_id"), table_name="pack_fire_events")
    op.drop_index(op.f("ix_pack_fire_events_studio_id"), table_name="pack_fire_events")
    op.drop_index(op.f("ix_pack_fire_events_completion_id"), table_name="pack_fire_events")
    op.drop_index(op.f("ix_pack_fire_events_id"), table_name="pack_fire_events")
    op.drop_table("pack_fire_events")
