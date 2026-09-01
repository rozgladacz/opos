"""Tryby punktów, opisów i małej bitwy dla rozpiski."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0002"
down_revision: Union[str, None] = "20260803_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rosters",
        sa.Column("simple_points_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "rosters",
        sa.Column("collapse_descriptions", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "rosters",
        sa.Column("small_battle_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("rosters", "small_battle_enabled")
    op.drop_column("rosters", "collapse_descriptions")
    op.drop_column("rosters", "simple_points_enabled")
