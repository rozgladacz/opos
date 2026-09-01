"""Zastąp prosty tryb liczbową skalą punktów."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session


revision: str = "20260817_0003"
down_revision: Union[str, None] = "20260803_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rosters",
        sa.Column(
            "points_scale", sa.Integer(), nullable=False, server_default="10"
        ),
    )
    op.execute(
        "UPDATE rosters SET points_scale = "
        "CASE WHEN simple_points_enabled = 1 THEN 10 ELSE 1 END"
    )
    from app.services.opos_units import convert_legacy_simple_points

    session = Session(bind=op.get_bind())
    convert_legacy_simple_points(session)
    session.flush()
    op.drop_column("rosters", "simple_points_enabled")


def downgrade() -> None:
    op.add_column(
        "rosters",
        sa.Column(
            "simple_points_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "UPDATE rosters SET simple_points_enabled = "
        "CASE WHEN points_scale = 10 THEN 1 ELSE 0 END"
    )
    op.drop_column("rosters", "points_scale")
