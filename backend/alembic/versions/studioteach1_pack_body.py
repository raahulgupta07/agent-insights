"""studio_bound_packs.pack_body: self-contained user-authored packs (Teach Box)

Revision ID: studioteach1
Revises: studiopack1
Create Date: 2026-06-24

Adds a nullable JSON `pack_body` column to `studio_bound_packs`. Library packs
(source='pack') live as yaml files and are loaded by the registry, so their
body is null here. USER-authored packs (source='user', built by the Teach Box)
have no yaml file on disk — the whole declarative pack dict (id/name/method_text
/required_inputs/trigger_hints/output_spec/format) is stored inline in
`pack_body` so `runtime.resolve_injection` can reconstruct the pack when the
registry has no file for that id. Fully additive + gated by flags.DOMAIN_PACKS.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "studioteach1"
down_revision: Union[str, None] = "studiopack1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("studio_bound_packs", sa.Column("pack_body", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("studio_bound_packs", "pack_body")
