"""Idempotent normalization of snapshots saved under earlier OPOS v1 rules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_MOVED_WEAPON_ABILITIES: dict[str, tuple[str, ...]] = {
    "charge": ("melee",),
    "prepared": ("short", "long"),
}
_RENAMED_PASSIVE_ABILITIES = {"guardian": "breakthrough"}


def normalize_snapshot_abilities(
    passive_abilities: list[str], profiles: dict[str, Any]
) -> tuple[list[str], dict[str, Any], bool]:
    """Normalize legacy passive names and move weapon abilities to profiles."""
    normalized_passives = list(
        dict.fromkeys(
            _RENAMED_PASSIVE_ABILITIES.get(slug, slug)
            for slug in passive_abilities
            if slug not in _MOVED_WEAPON_ABILITIES
        )
    )
    moved = [slug for slug in passive_abilities if slug in _MOVED_WEAPON_ABILITIES]
    renamed = normalized_passives != [
        slug for slug in passive_abilities if slug not in _MOVED_WEAPON_ABILITIES
    ]
    if not moved:
        return normalized_passives, profiles, renamed

    normalized_profiles = deepcopy(profiles)
    for slug in moved:
        for range_slug in _MOVED_WEAPON_ABILITIES[slug]:
            profile = normalized_profiles.get(range_slug)
            if not isinstance(profile, dict):
                continue
            abilities = list(profile.get("abilities", []))
            if slug not in abilities:
                abilities.append(slug)
            profile["abilities"] = abilities
    return normalized_passives, normalized_profiles, True
