"""SSOT serializacji snapshotów profili OPOS między API i ORM."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from app import models
from app.services.opos_rules import (
    QuoteBreakdown,
    QuoteValidationError,
    UnitQuoteInput,
    calculate_unit_quote,
    canonicalize_unit_input,
    normalize_snapshot_abilities,
)


OPOS_1_2_USER_VERSION = 10200
OPOS_1_3_USER_VERSION = 10300
OPOS_V3_USER_VERSION = 30000
OPOS_V3_1_USER_VERSION = 30100


class UnitSnapshot(Protocol):
    name: str
    models_per_unit: int
    defense: object
    toughness: object
    passive_abilities_json: str
    special_abilities_json: str
    profiles_json: str


def _json_dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def request_from_snapshot(
    snapshot: UnitSnapshot,
    *,
    unit_copies: int = 1,
    custom_stats_enabled: bool,
    points_scale: int = 1,
    small_battle_enabled: bool = False,
) -> UnitQuoteInput:
    passive_abilities, profiles, _ = normalize_snapshot_abilities(
        json.loads(snapshot.passive_abilities_json),
        json.loads(snapshot.profiles_json),
    )
    return UnitQuoteInput.model_validate(
        {
            "name": snapshot.name,
            "models_per_unit": snapshot.models_per_unit,
            "unit_copies": unit_copies,
            "defense": snapshot.defense,
            "toughness": snapshot.toughness,
            "passive_abilities": passive_abilities,
            "special_abilities": json.loads(snapshot.special_abilities_json),
            "profiles": profiles,
            "custom_stats_enabled": custom_stats_enabled,
            "points_scale": points_scale,
            "small_battle_enabled": small_battle_enabled,
        }
    )


def normalize_legacy_snapshot_records(session: Session) -> int:
    """Persist legacy ability names and categories in existing snapshots."""
    changed = 0
    for model in (models.UnitTemplate, models.RosterUnit):
        for snapshot in session.scalars(select(model)):
            passive_abilities, profiles, was_changed = normalize_snapshot_abilities(
                json.loads(snapshot.passive_abilities_json),
                json.loads(snapshot.profiles_json),
            )
            special_abilities = json.loads(snapshot.special_abilities_json)
            normalized_specials = [
                {
                    **selection,
                    "target_slug": "breakthrough",
                }
                if selection.get("target_slug") == "guardian"
                else selection
                for selection in special_abilities
            ]
            special_changed = normalized_specials != special_abilities
            if was_changed:
                snapshot.passive_abilities_json = _json_dump(passive_abilities)
                snapshot.profiles_json = _json_dump(profiles)
            if special_changed:
                snapshot.special_abilities_json = _json_dump(normalized_specials)
            if was_changed or special_changed:
                changed += 1
    return changed


def migrate_opos_1_2(session: Session) -> int:
    """Atomically scale Życie and recalculate snapshots for OPOS 1.2."""
    if session.get_bind().dialect.name != "sqlite":
        return 0
    current_version = int(session.execute(text("PRAGMA user_version")).scalar_one())
    if current_version >= OPOS_1_2_USER_VERSION:
        return 0

    normalize_legacy_snapshot_records(session)
    changed = 0
    for template in session.scalars(select(models.UnitTemplate)):
        template.toughness = Decimal(template.toughness) * Decimal("2")
        changed += 1

    rosters = session.scalars(
        select(models.Roster).options(selectinload(models.Roster.roster_units))
    ).all()
    for roster in rosters:
        for unit in roster.roster_units:
            unit.toughness = Decimal(unit.toughness) * Decimal("2")
            request = request_from_snapshot(
                unit,
                unit_copies=unit.unit_copies,
                custom_stats_enabled=roster.custom_stats_enabled,
                small_battle_enabled=roster.small_battle_enabled,
            )
            quote = calculate_unit_quote(request, ruleset_version=roster.ruleset_version)
            apply_request_to_roster_unit(unit, request, quote)
            changed += 1

    if changed:
        session.flush()
    session.execute(text(f"PRAGMA user_version = {OPOS_1_2_USER_VERSION}"))
    return changed


def convert_legacy_simple_points(session: Session) -> int:
    """Restore base points for rosters persisted by the former boolean mode."""
    if session.get_bind().dialect.name != "sqlite":
        return 0
    columns = {
        row[1] for row in session.execute(text("PRAGMA table_info(rosters)"))
    }
    if "simple_points_enabled" not in columns:
        return 0
    roster_ids = tuple(
        session.execute(
            text("SELECT id FROM rosters WHERE simple_points_enabled = 1")
        ).scalars()
    )
    if not roster_ids:
        return 0
    changed = 0
    rosters = session.scalars(
        select(models.Roster)
        .options(selectinload(models.Roster.roster_units))
        .where(models.Roster.id.in_(roster_ids))
    ).all()
    for roster in rosters:
        if roster.points_limit is not None:
            roster.points_limit *= 10
        for unit in roster.roster_units:
            request = request_from_snapshot(
                unit,
                unit_copies=unit.unit_copies,
                custom_stats_enabled=roster.custom_stats_enabled,
                small_battle_enabled=roster.small_battle_enabled,
            )
            quote = calculate_unit_quote(
                request, ruleset_version=roster.ruleset_version
            )
            apply_request_to_roster_unit(unit, request, quote)
            changed += 1
    session.flush()
    return changed


def migrate_opos_1_3(session: Session) -> int:
    """Replace the simple-points flag with a divisor and restore base values."""
    if session.get_bind().dialect.name != "sqlite":
        return 0
    current_version = int(session.execute(text("PRAGMA user_version")).scalar_one())
    if current_version >= OPOS_1_3_USER_VERSION:
        return 0
    changed = convert_legacy_simple_points(session)
    session.execute(text(f"PRAGMA user_version = {OPOS_1_3_USER_VERSION}"))
    return changed


def migrate_opos_v3(session: Session) -> int:
    """Atomically validate, reprice and move all OPOS snapshots to rules v3."""
    if session.get_bind().dialect.name != "sqlite":
        return 0
    current_version = int(session.execute(text("PRAGMA user_version")).scalar_one())
    if current_version >= OPOS_V3_USER_VERSION:
        return 0

    normalize_legacy_snapshot_records(session)
    changed = 0
    for template in session.scalars(select(models.UnitTemplate)):
        standard_request = request_from_snapshot(
            template,
            unit_copies=1,
            custom_stats_enabled=False,
        )
        try:
            calculate_unit_quote(standard_request, ruleset_version="v3")
        except QuoteValidationError:
            custom_request = standard_request.model_copy(
                update={"custom_stats_enabled": True}
            )
            try:
                calculate_unit_quote(custom_request, ruleset_version="v3")
            except QuoteValidationError as exc:
                raise RuntimeError(
                    f"Szablon '{template.name}' nie jest zgodny z OPOS v3: {exc}"
                ) from exc
        template.ruleset_version = "v3"
        changed += 1

    rosters = session.scalars(
        select(models.Roster).options(selectinload(models.Roster.roster_units))
    ).all()
    for roster in rosters:
        for unit in roster.roster_units:
            request = request_from_snapshot(
                unit,
                unit_copies=unit.unit_copies,
                custom_stats_enabled=roster.custom_stats_enabled,
                small_battle_enabled=roster.small_battle_enabled,
            )
            try:
                quote = calculate_unit_quote(request, ruleset_version="v3")
            except QuoteValidationError as exc:
                raise RuntimeError(
                    f"Oddział '{unit.name}' w rozpisce '{roster.name}' "
                    f"nie jest zgodny z OPOS v3: {exc}"
                ) from exc
            apply_request_to_roster_unit(unit, request, quote)
            changed += 1
        roster.ruleset_version = "v3"

    if changed:
        session.flush()
    session.execute(text(f"PRAGMA user_version = {OPOS_V3_USER_VERSION}"))
    return changed


def migrate_opos_v3_1(session: Session) -> int:
    """Move the temporary Army-level Tarcza/Pięść option to each roster."""
    if session.get_bind().dialect.name != "sqlite":
        return 0
    current_version = int(session.execute(text("PRAGMA user_version")).scalar_one())
    if current_version >= OPOS_V3_1_USER_VERSION:
        return 0

    army_columns = {
        row[1] for row in session.execute(text("PRAGMA table_info(armies)"))
    }
    changed = 0
    if "shield_fist_enabled" in army_columns:
        result = session.execute(
            text(
                "UPDATE rosters SET shield_fist_enabled = COALESCE(("
                "SELECT armies.shield_fist_enabled FROM armies "
                "WHERE armies.id = rosters.army_id"
                "), 0)"
            )
        )
        changed = max(result.rowcount or 0, 0)
    session.execute(text(f"PRAGMA user_version = {OPOS_V3_1_USER_VERSION}"))
    return changed


def _snapshot_values(request: UnitQuoteInput) -> dict[str, object]:
    request = canonicalize_unit_input(request)
    return {
        "name": request.name,
        "models_per_unit": request.models_per_unit,
        "defense": request.defense,
        "toughness": request.toughness,
        "passive_abilities_json": _json_dump(list(request.passive_abilities)),
        "special_abilities_json": _json_dump(
            [item.model_dump(mode="json", exclude_none=True) for item in request.special_abilities]
        ),
        "profiles_json": _json_dump(request.profiles.model_dump(mode="json")),
    }


def apply_request_to_roster_unit(
    unit: models.RosterUnit,
    request: UnitQuoteInput,
    quote: QuoteBreakdown,
) -> None:
    for key, value in _snapshot_values(request).items():
        setattr(unit, key, value)
    unit.unit_copies = request.unit_copies
    unit.unit_cost = int(quote.unscaled_unit_cost)


def create_template_from_roster_unit(
    roster_unit: models.RosterUnit,
    *,
    army: models.Army,
    position: int,
    ruleset_version: str,
) -> models.UnitTemplate:
    return models.UnitTemplate(
        army=army,
        owner_id=army.owner_id,
        name=roster_unit.name,
        models_per_unit=roster_unit.models_per_unit,
        defense=roster_unit.defense,
        toughness=roster_unit.toughness,
        passive_abilities_json=roster_unit.passive_abilities_json,
        special_abilities_json=roster_unit.special_abilities_json,
        profiles_json=roster_unit.profiles_json,
        ruleset_version=ruleset_version,
        position=position,
    )


def update_template_from_roster_unit(
    template: models.UnitTemplate,
    roster_unit: models.RosterUnit,
    *,
    ruleset_version: str,
) -> None:
    template.name = roster_unit.name
    template.models_per_unit = roster_unit.models_per_unit
    template.defense = roster_unit.defense
    template.toughness = roster_unit.toughness
    template.passive_abilities_json = roster_unit.passive_abilities_json
    template.special_abilities_json = roster_unit.special_abilities_json
    template.profiles_json = roster_unit.profiles_json
    template.ruleset_version = ruleset_version


def snapshot_requires_custom_stats(
    snapshot: UnitSnapshot,
    *,
    ruleset_version: str,
    small_battle_enabled: bool = False,
) -> bool:
    try:
        request = request_from_snapshot(
            snapshot,
            unit_copies=1,
            custom_stats_enabled=False,
            small_battle_enabled=small_battle_enabled,
        )
        calculate_unit_quote(request, ruleset_version=ruleset_version)
    except QuoteValidationError:
        return True
    return False


def template_requires_custom_stats(
    template: models.UnitTemplate, *, small_battle_enabled: bool = False
) -> bool:
    return snapshot_requires_custom_stats(
        template,
        ruleset_version=template.ruleset_version,
        small_battle_enabled=small_battle_enabled,
    )
