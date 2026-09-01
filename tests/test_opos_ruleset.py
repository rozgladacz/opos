from decimal import Decimal

import pytest

from app.services.opos_rules import load_opos_ruleset


def test_ruleset_is_cached_and_complete() -> None:
    first = load_opos_ruleset()
    second = load_opos_ruleset()

    assert first is second
    assert first.version == "3.0.0"
    assert first.stat_icons["models"] == "models"
    assert set(first.ranges) == {"melee", "short", "long"}
    assert {item.slug for item in first.abilities_of("passive")} == {
        "hero", "ambush", "scout", "agile", "fast", "immobile", "clumsy", "jump",
        "dodge", "parry", "steadfast", "patient",
        "breakthrough", "counterattack", "invulnerable", "sentinel", "airplane",
    }
    assert {item.slug for item in first.abilities_of("special")} == {
        "patching", "aura", "order", "transport",
    }
    assert {item.slug for item in first.abilities_of("weapon")} == {
        "area", "deadly", "double", "reload", "artillery", "charge",
        "prepared", "encirclement", "single-use",
    }
    assert all(item.icon and item.description for item in first.abilities)


def test_current_rule_changes_are_in_yaml() -> None:
    abilities = load_opos_ruleset().abilities_by_slug

    ruleset = load_opos_ruleset()
    assert ruleset.standard_stats.toughness == tuple(
        Decimal(value) for value in (2, 4, 6, 12, 18, 24)
    )
    assert ruleset.formula.weapon_factor == Decimal("6")
    assert ruleset.ranges["melee"].multiplier == Decimal("0.5")
    assert abilities["airplane"].effects.ability_cost_delta == Decimal("-1")
    assert abilities["airplane"].effects.profile_multipliers == {
        "melee": Decimal("0"),
        "short": Decimal("0"),
        "long": Decimal("1.6"),
    }
    assert abilities["airplane"].aura_eligible is False
    assert abilities["clumsy"].description == "Nie może wchodzić na Wysoki teren."
    assert abilities["clumsy"].effects.ability_cost_delta == Decimal("-0.5")
    assert abilities["clumsy"].aura_eligible is False
    assert load_opos_ruleset().ranges["short"].multiplier == Decimal("0.6")
    assert load_opos_ruleset().ranges["long"].multiplier == Decimal("1")
    assert abilities["deadly"].effects.weapon_multiplier == Decimal("4")
    assert abilities["deadly"].effects.small_battle_weapon_multiplier == Decimal("8")
    assert "6 lub mniej" in abilities["deadly"].description
    assert "12 lub mniej" in abilities["deadly"].small_battle_description
    assert "zadaj 12 ran" in abilities["deadly"].small_battle_description
    assert abilities["transport"].effects.ability_cost_delta == Decimal("2")
    assert abilities["transport"].effects.conditional_ability_costs[0].delta == Decimal("2")
    assert abilities["double"].description == "Każdy sukces liczy się również jako remis."
    assert abilities["double"].effects.weapon_multiplier == Decimal("1.5")
    assert abilities["charge"].category == "weapon"
    assert abilities["charge"].allowed_ranges == ("melee",)
    assert abilities["charge"].effects.weapon_multiplier == Decimal("1.4")
    assert abilities["prepared"].category == "weapon"
    assert abilities["prepared"].allowed_ranges == ("short", "long")
    assert abilities["prepared"].effects.weapon_multiplier == Decimal("1.4")
    assert abilities["invulnerable"].effects.defense_bonus == Decimal("0.25")
    assert abilities["sentinel"].effects.ability_cost_delta == Decimal("1")
    assert abilities["encirclement"].effects.weapon_multiplier == Decimal("1.4")
    assert abilities["single-use"].effects.weapon_multiplier == Decimal("0.4")
    assert abilities["reload"].aura_eligible is False
    assert abilities["single-use"].aura_eligible is False
    assert abilities["area"].small_battle_description
    assert "guardian" not in abilities
    assert ruleset.custom_stats.defense.minimum == Decimal("1")
    assert ruleset.custom_stats.defense.maximum == Decimal("6")
    assert ruleset.custom_stats.strength.minimum == Decimal("-1")
    assert ruleset.custom_stats.strength.maximum == Decimal("4")
    assert ruleset.custom_stats.toughness.maximum == Decimal("99")


def test_aura_target_list_is_exact() -> None:
    assert {item.slug for item in load_opos_ruleset().aura_targets} == {
        "agile", "fast", "jump", "dodge", "parry", "steadfast", "patient",
        "breakthrough", "counterattack", "invulnerable", "sentinel",
        "area", "deadly", "encirclement", "double", "artillery", "charge",
        "prepared",
    }


def test_unknown_ruleset_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        load_opos_ruleset("v999")
