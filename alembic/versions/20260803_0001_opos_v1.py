"""Początkowy, świeży schemat OPOS v1."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "armies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_armies_owner_id", "armies", ["owner_id"])
    op.create_table(
        "unit_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("army_id", sa.Integer(), sa.ForeignKey("armies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("models_per_unit", sa.Integer(), nullable=False),
        sa.Column("defense", sa.Numeric(10, 3), nullable=False),
        sa.Column("toughness", sa.Numeric(10, 3), nullable=False),
        sa.Column("passive_abilities_json", sa.Text(), nullable=False),
        sa.Column("special_abilities_json", sa.Text(), nullable=False),
        sa.Column("profiles_json", sa.Text(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_unit_templates_army_id", "unit_templates", ["army_id"])
    op.create_index("ix_unit_templates_owner_id", "unit_templates", ["owner_id"])
    op.create_index("ix_unit_templates_army_position", "unit_templates", ["army_id", "position"])
    op.create_table(
        "rosters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("army_id", sa.Integer(), sa.ForeignKey("armies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("points_limit", sa.Integer(), nullable=True),
        sa.Column("ruleset_version", sa.String(length=20), nullable=False),
        sa.Column("custom_stats_enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_rosters_owner_id", "rosters", ["owner_id"])
    op.create_index("ix_rosters_army_id", "rosters", ["army_id"])
    op.create_table(
        "roster_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("roster_id", sa.Integer(), sa.ForeignKey("rosters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_template_id", sa.Integer(), sa.ForeignKey("unit_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("models_per_unit", sa.Integer(), nullable=False),
        sa.Column("unit_copies", sa.Integer(), nullable=False),
        sa.Column("defense", sa.Numeric(10, 3), nullable=False),
        sa.Column("toughness", sa.Numeric(10, 3), nullable=False),
        sa.Column("passive_abilities_json", sa.Text(), nullable=False),
        sa.Column("special_abilities_json", sa.Text(), nullable=False),
        sa.Column("profiles_json", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_roster_units_roster_id", "roster_units", ["roster_id"])
    op.create_index("ix_roster_units_source_template_id", "roster_units", ["source_template_id"])
    op.create_index("ix_roster_units_roster_position", "roster_units", ["roster_id", "position"])


def downgrade() -> None:
    op.drop_table("roster_units")
    op.drop_table("rosters")
    op.drop_table("unit_templates")
    op.drop_table("armies")
    op.drop_table("users")
