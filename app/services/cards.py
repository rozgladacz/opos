"""View-model kart OPOS współdzielony przez HTML i PDF."""

from __future__ import annotations

import json
from collections.abc import Iterable

from app import models
from app.services.opos_rules import (
    display_number,
    format_stat_value,
    load_opos_ruleset,
    normalize_snapshot_abilities,
    scale_points,
    stat_label,
)


PRIMARY_ABILITY_LIMIT = 6
CONTINUATION_ABILITY_LIMIT = 8


def build_ability_payloads(
    unit: models.RosterUnit,
    *,
    ruleset_version: str,
    small_battle_enabled: bool = False,
) -> list[dict[str, str]]:
    ruleset = load_opos_ruleset(ruleset_version)
    by_slug = ruleset.abilities_by_slug
    result: list[dict[str, str]] = []
    passives, _, _ = normalize_snapshot_abilities(
        json.loads(unit.passive_abilities_json),
        json.loads(unit.profiles_json),
    )

    def description(slug: str) -> str:
        definition = by_slug[slug]
        if small_battle_enabled and definition.small_battle_description:
            return definition.small_battle_description
        return definition.description

    for slug in passives:
        definition = by_slug[slug]
        result.append(
            {
                "slug": slug,
                "name": definition.name,
                "description": description(slug),
                "icon": definition.icon,
            }
        )
    for selection in json.loads(unit.special_abilities_json):
        definition = by_slug[selection["slug"]]
        name = definition.name
        if selection.get("target_slug"):
            target = by_slug[selection["target_slug"]]
            name = f"{name} ({target.name})"
        result.append(
            {
                "slug": selection["slug"],
                "name": name,
                "description": description(selection["slug"]),
                "icon": definition.icon,
            }
        )
    return result


def build_attack_ability_payloads(
    unit: models.RosterUnit,
    *,
    ruleset_version: str,
    small_battle_enabled: bool = False,
) -> list[dict[str, str]]:
    ruleset = load_opos_ruleset(ruleset_version)
    if not ruleset.version.startswith("3."):
        return []
    by_slug = ruleset.abilities_by_slug
    _, profiles, _ = normalize_snapshot_abilities(
        json.loads(unit.passive_abilities_json),
        json.loads(unit.profiles_json),
    )
    profile_names_by_ability: dict[str, list[str]] = {}
    for range_slug in ("melee", "short", "long"):
        for slug in profiles[range_slug].get("abilities", []):
            profile_names_by_ability.setdefault(slug, []).append(
                ruleset.ranges[range_slug].name
            )
    result: list[dict[str, str]] = []
    for slug, profile_names in profile_names_by_ability.items():
        definition = by_slug[slug]
        description = (
            definition.small_battle_description
            if small_battle_enabled and definition.small_battle_description
            else definition.description
        )
        result.append(
            {
                "slug": slug,
                "name": f"{definition.name} ({', '.join(profile_names)})",
                "description": description,
                "icon": definition.icon,
            }
        )
    return result


def build_profile_payloads(
    unit: models.RosterUnit,
    *,
    ruleset_version: str,
    shield_fist_enabled: bool = False,
) -> list[dict[str, object]]:
    ruleset = load_opos_ruleset(ruleset_version)
    by_slug = ruleset.abilities_by_slug
    _, profiles, _ = normalize_snapshot_abilities(
        json.loads(unit.passive_abilities_json),
        json.loads(unit.profiles_json),
    )
    result: list[dict[str, object]] = []
    for range_slug in ("melee", "short", "long"):
        profile = profiles[range_slug]
        result.append(
            {
                "range": range_slug,
                "name": ruleset.ranges[range_slug].name,
                "icon": ruleset.ranges[range_slug].icon,
                "active": int(profile["dice"]) > 0,
                "dice": int(profile["dice"]),
                "strength": format_stat_value(
                    "strength",
                    profile["strength"],
                    shield_fist_enabled=shield_fist_enabled,
                ),
                "strength_label": stat_label(
                    "strength", shield_fist_enabled=shield_fist_enabled
                ),
                "abilities": [
                    {
                        "name": by_slug[slug].name,
                        "icon": by_slug[slug].icon,
                    }
                    for slug in profile.get("abilities", [])
                ],
            }
        )
    return result


def build_unit_cards(
    unit: models.RosterUnit,
    *,
    ruleset_version: str,
    points_scale: int = 1,
    small_battle_enabled: bool = False,
    shield_fist_enabled: bool = False,
) -> list[dict[str, object]]:
    abilities = build_ability_payloads(
        unit,
        ruleset_version=ruleset_version,
        small_battle_enabled=small_battle_enabled,
    )
    attack_abilities = build_attack_ability_payloads(
        unit,
        ruleset_version=ruleset_version,
        small_battle_enabled=small_battle_enabled,
    )
    primary_limit = max(PRIMARY_ABILITY_LIMIT - len(attack_abilities), 0)
    continuation_limit = CONTINUATION_ABILITY_LIMIT
    cards: list[dict[str, object]] = [
        {
            "kind": "profile",
            "name": unit.name,
            "unit_cost": scale_points(unit.unit_cost, points_scale),
            "models_per_unit": unit.models_per_unit,
            "defense": format_stat_value(
                "defense",
                unit.defense,
                shield_fist_enabled=shield_fist_enabled,
            ),
            "defense_label": stat_label(
                "defense", shield_fist_enabled=shield_fist_enabled
            ),
            "toughness": display_number(unit.toughness),
            "abilities": abilities[:primary_limit],
            "attack_abilities": attack_abilities,
            "profiles": build_profile_payloads(
                unit,
                ruleset_version=ruleset_version,
                shield_fist_enabled=shield_fist_enabled,
            ),
        }
    ]
    remaining = abilities[primary_limit:]
    for start in range(0, len(remaining), continuation_limit):
        cards.append(
            {
                "kind": "continuation",
                "name": unit.name,
                "unit_cost": scale_points(unit.unit_cost, points_scale),
                "models_per_unit": unit.models_per_unit,
                "abilities": remaining[start : start + continuation_limit],
                "continuation_number": len(cards),
            }
        )
    return cards


def build_card_pages(
    units: Iterable[models.RosterUnit],
    *,
    ruleset_version: str,
    points_scale: int = 1,
    small_battle_enabled: bool = False,
    shield_fist_enabled: bool = False,
) -> list[list[dict[str, object] | None]]:
    cards = [
        card
        for unit in units
        for card in build_unit_cards(
            unit,
            ruleset_version=ruleset_version,
            points_scale=points_scale,
            small_battle_enabled=small_battle_enabled,
            shield_fist_enabled=shield_fist_enabled,
        )
    ]
    pages: list[list[dict[str, object] | None]] = []
    for start in range(0, len(cards), 4):
        page: list[dict[str, object] | None] = cards[start : start + 4]
        page.extend([None] * (4 - len(page)))
        pages.append(page)
    return pages
