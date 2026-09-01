from decimal import Decimal

from app import models
from app.services.opos_rules import (
    AttackProfileInput,
    AttackProfilesInput,
    SpecialAbilityInput,
    UnitQuoteInput,
    calculate_unit_quote,
    normalize_snapshot_abilities,
)
from app.services.opos_units import (
    apply_request_to_roster_unit,
    create_template_from_roster_unit,
    request_from_snapshot,
    template_requires_custom_stats,
    update_template_from_roster_unit,
)


def _request(*, name: str = "Straż", defense: Decimal = Decimal("4")) -> UnitQuoteInput:
    return UnitQuoteInput(
        name=name,
        models_per_unit=3,
        unit_copies=2,
        defense=defense,
        toughness=2,
        passive_abilities=("steadfast",),
        special_abilities=(SpecialAbilityInput(slug="transport"),),
        profiles=AttackProfilesInput(
            melee=AttackProfileInput(dice=1, strength=1),
            short=AttackProfileInput(dice=2, strength=0, abilities=("double",)),
            long=AttackProfileInput(dice=0, strength=0),
        ),
        custom_stats_enabled=defense not in {Decimal("3"), Decimal("4"), Decimal("5")},
    )


def _roster_unit(request: UnitQuoteInput) -> models.RosterUnit:
    result = models.RosterUnit(
        name="",
        models_per_unit=1,
        unit_copies=1,
        defense=1,
        toughness=1,
        profiles_json="{}",
        unit_cost=0,
        position=0,
    )
    apply_request_to_roster_unit(result, request, calculate_unit_quote(request))
    return result


def test_template_copy_is_an_independent_snapshot_without_copy_count() -> None:
    unit = _roster_unit(_request())
    army = models.Army(name="Biblioteka", owner_id=7)
    template = create_template_from_roster_unit(
        unit, army=army, position=0, ruleset_version="v1"
    )

    unit.name = "Zmieniony"
    unit.passive_abilities_json = "[]"
    restored = request_from_snapshot(
        template, unit_copies=1, custom_stats_enabled=False
    )

    assert restored.name == "Straż"
    assert restored.unit_copies == 1
    assert restored.passive_abilities == ("steadfast",)


def test_explicit_template_update_copies_current_snapshot() -> None:
    unit = _roster_unit(_request(name="Nowa nazwa"))
    template = models.UnitTemplate(
        name="Stara nazwa",
        owner_id=1,
        army_id=1,
        models_per_unit=1,
        defense=3,
        toughness=1,
        profiles_json="{}",
        position=0,
    )

    update_template_from_roster_unit(template, unit, ruleset_version="v1")

    assert template.name == "Nowa nazwa"
    assert template.models_per_unit == 3
    assert template.profiles_json == unit.profiles_json


def test_custom_template_is_detected_before_standard_roster_copy() -> None:
    unit = _roster_unit(_request(defense=Decimal("6")))
    template = create_template_from_roster_unit(
        unit,
        army=models.Army(name="Biblioteka", owner_id=1),
        position=0,
        ruleset_version="v1",
    )

    assert template_requires_custom_stats(template) is True


def test_legacy_charge_and_prepared_are_moved_to_attack_profiles() -> None:
    passives, profiles, changed = normalize_snapshot_abilities(
        ["steadfast", "charge", "prepared"],
        {
            "melee": {"dice": 1, "strength": 0, "abilities": []},
            "short": {"dice": 1, "strength": 0, "abilities": []},
            "long": {"dice": 0, "strength": 0, "abilities": []},
        },
    )

    assert changed is True
    assert passives == ["steadfast"]
    assert profiles["melee"]["abilities"] == ["charge"]
    assert profiles["short"]["abilities"] == ["prepared"]
    assert profiles["long"]["abilities"] == ["prepared"]
    assert normalize_snapshot_abilities(passives, profiles) == (
        passives,
        profiles,
        False,
    )


def test_legacy_guardian_is_mapped_to_breakthrough_once() -> None:
    profiles = {
        "melee": {"dice": 0, "strength": 0, "abilities": []},
        "short": {"dice": 0, "strength": 0, "abilities": []},
        "long": {"dice": 0, "strength": 0, "abilities": []},
    }

    passives, normalized_profiles, changed = normalize_snapshot_abilities(
        ["guardian", "breakthrough"], profiles
    )

    assert passives == ["breakthrough"]
    assert normalized_profiles is profiles
    assert changed is True
