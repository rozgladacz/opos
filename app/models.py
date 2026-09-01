"""Relacyjny model danych OPOS v1."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_custom_stats_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    default_points_scale: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    default_collapse_descriptions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    default_small_battle_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    default_shield_fist_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    armies: Mapped[list["Army"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    templates: Mapped[list["UnitTemplate"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    rosters: Mapped[list["Roster"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Army(TimestampMixin, Base):
    __tablename__ = "armies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner: Mapped[User] = relationship(back_populates="armies")
    templates: Mapped[list["UnitTemplate"]] = relationship(
        back_populates="army",
        cascade="all, delete-orphan",
        order_by="UnitTemplate.position",
    )
    rosters: Mapped[list["Roster"]] = relationship(back_populates="army")


class UnitTemplate(TimestampMixin, Base):
    __tablename__ = "unit_templates"
    __table_args__ = (
        Index("ix_unit_templates_army_position", "army_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    army_id: Mapped[int] = mapped_column(
        ForeignKey("armies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    models_per_unit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    defense: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    toughness: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    passive_abilities_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    special_abilities_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    profiles_json: Mapped[str] = mapped_column(Text, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="v3"
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    army: Mapped[Army] = relationship(back_populates="templates")
    owner: Mapped[User] = relationship(back_populates="templates")
    roster_units: Mapped[list["RosterUnit"]] = relationship(
        back_populates="source_template"
    )


class Roster(TimestampMixin, Base):
    __tablename__ = "rosters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    army_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("armies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    points_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ruleset_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="v3"
    )
    custom_stats_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    points_scale: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    collapse_descriptions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    small_battle_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    shield_fist_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    owner: Mapped[User] = relationship(back_populates="rosters")
    army: Mapped[Optional[Army]] = relationship(back_populates="rosters")
    roster_units: Mapped[list["RosterUnit"]] = relationship(
        back_populates="roster",
        cascade="all, delete-orphan",
        order_by="RosterUnit.position",
    )

    @property
    def total_cost(self) -> int:
        return sum(item.unit_cost * item.unit_copies for item in self.roster_units)


class RosterUnit(TimestampMixin, Base):
    __tablename__ = "roster_units"
    __table_args__ = (
        Index("ix_roster_units_roster_position", "roster_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    roster_id: Mapped[int] = mapped_column(
        ForeignKey("rosters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("unit_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    models_per_unit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_copies: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    defense: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    toughness: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    passive_abilities_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    special_abilities_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    profiles_json: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[int] = mapped_column(Integer, nullable=False)

    roster: Mapped[Roster] = relationship(back_populates="roster_units")
    source_template: Mapped[Optional[UnitTemplate]] = relationship(
        back_populates="roster_units"
    )

    @property
    def entry_cost(self) -> int:
        return self.unit_cost * self.unit_copies
