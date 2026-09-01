from decimal import Decimal

import pytest

from app.services.opos_rules import (
    AttackProfileInput,
    AttackProfilesInput,
    QuoteValidationError,
    SpecialAbilityInput,
    UnitQuoteInput,
    calculate_unit_quote,
    scale_points,
)


def unit_input(**overrides: object) -> UnitQuoteInput:
    payload: dict[str, object] = {
        "name": "Straż",
        "models_per_unit": 1,
        "unit_copies": 1,
        "defense": 3,
        "toughness": 2,
        "profiles": AttackProfilesInput(
            melee=AttackProfileInput(dice=1, strength=0),
            short=AttackProfileInput(dice=0, strength=0),
            long=AttackProfileInput(dice=0, strength=0),
        ),
    }
    payload.update(overrides)
    return UnitQuoteInput.model_validate(payload)


def test_golden_basic_unit_has_no_intermediate_rounding() -> None:
    quote = calculate_unit_quote(unit_input())

    assert quote.toughness_sum == Decimal("2")
    assert quote.effective_defense == Decimal("3")
    assert quote.defense_multiplier == Decimal("1.24")
    assert quote.base_cost == Decimal("14.88")
    assert quote.weapon_cost == Decimal("6.0")
    assert quote.raw_unit_cost == Decimal("21.2976")
    assert quote.rounded_unit_cost == Decimal("21")


def test_models_and_copies_are_applied_at_distinct_stages() -> None:
    quote = calculate_unit_quote(unit_input(models_per_unit=3, unit_copies=4))

    assert quote.toughness_sum == Decimal("6")
    assert quote.base_cost == Decimal("44.64")
    assert quote.weapon_cost == Decimal("18.0")
    assert quote.rounded_unit_cost == Decimal("64")
    assert quote.entry_cost == Decimal("256")


def test_points_scale_divides_cost_dynamically_and_keeps_unscaled_cost() -> None:
    regular = calculate_unit_quote(unit_input(models_per_unit=25, defense=5, toughness=6))
    scaled = calculate_unit_quote(
        unit_input(
            models_per_unit=25,
            defense=5,
            toughness=6,
            points_scale=10,
        )
    )

    assert scaled.points_scale == Decimal("10")
    assert scaled.unscaled_unit_cost == regular.unscaled_unit_cost
    assert scaled.raw_unit_cost == regular.raw_unit_cost / Decimal("10")
    assert scaled.raw_unit_cost == Decimal("235.32000")
    assert scaled.rounded_unit_cost == Decimal("235")
    assert scaled.base_cost == regular.base_cost / Decimal("10")


def test_stored_points_are_scaled_with_half_up_rounding() -> None:
    assert scale_points(505, 10) == 51
    assert scale_points(2353, 10) == 235
    assert scale_points(2355, 10) == 236
    assert scale_points(None, 10) is None


def test_small_battle_uses_doubled_standard_toughness_list() -> None:
    accepted = calculate_unit_quote(
        unit_input(toughness=36, small_battle_enabled=True)
    )
    assert accepted.toughness_sum == Decimal("36")

    with pytest.raises(QuoteValidationError, match="Życie"):
        calculate_unit_quote(
            unit_input(toughness=2, small_battle_enabled=True)
        )


def test_small_battle_doubles_patching_and_deadly_values() -> None:
    quote = calculate_unit_quote(
        unit_input(
            toughness=4,
            small_battle_enabled=True,
            special_abilities=(SpecialAbilityInput(slug="patching"),),
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(
                    dice=1, strength=0, abilities=("deadly",)
                ),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            ),
        )
    )

    assert quote.toughness_sum == Decimal("10")
    assert quote.profiles[0].ability_multiplier == Decimal("8")
    assert quote.profiles[0].cost_per_model == Decimal("24.0")


def test_hero_is_applied_before_patching() -> None:
    quote = calculate_unit_quote(
        unit_input(
            models_per_unit=2,
            toughness=6,
            passive_abilities=("hero",),
            special_abilities=(SpecialAbilityInput(slug="patching"),),
        )
    )

    assert quote.toughness_sum == Decimal("27")


def test_airplane_changes_ability_and_profile_costs() -> None:
    regular = calculate_unit_quote(unit_input())
    airplane = calculate_unit_quote(
        unit_input(
            passive_abilities=("airplane",),
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=0),
                short=AttackProfileInput(dice=1, strength=0),
                long=AttackProfileInput(dice=1, strength=0),
            ),
        )
    )

    assert airplane.ability_cost_modifier == Decimal("-1")
    assert airplane.base_cost < regular.base_cost
    assert [profile.cost_per_model for profile in airplane.profiles] == [
        Decimal("0.0"), Decimal("0.0"), Decimal("9.6"),
    ]
    assert airplane.weapon_cost == Decimal("19.2")


def test_clumsy_subtracts_half_from_ability_cost() -> None:
    regular = calculate_unit_quote(unit_input())
    clumsy = calculate_unit_quote(unit_input(passive_abilities=("clumsy",)))

    assert clumsy.ability_cost_modifier == Decimal("-0.5")
    assert clumsy.base_cost < regular.base_cost


def test_new_passive_abilities_apply_their_cost_effects() -> None:
    quote = calculate_unit_quote(
        unit_input(passive_abilities=("invulnerable", "sentinel"))
    )

    assert quote.effective_defense == Decimal("3.25")
    assert quote.ability_cost_modifier == Decimal("1")


def test_transport_costs_two_more_with_fast_agile_or_jump() -> None:
    quote = calculate_unit_quote(
        unit_input(
            passive_abilities=("fast",),
            special_abilities=(SpecialAbilityInput(slug="transport"),),
        )
    )

    assert quote.ability_cost_modifier == Decimal("5")


def test_incompatible_abilities_are_rejected_across_categories() -> None:
    with pytest.raises(QuoteValidationError, match="wzajemnie się wykluczają"):
        calculate_unit_quote(
            unit_input(passive_abilities=("immobile", "fast"))
        )

    with pytest.raises(QuoteValidationError, match="wzajemnie się wykluczają"):
        calculate_unit_quote(
            unit_input(
                passive_abilities=("immobile",),
                profiles=AttackProfilesInput(
                    melee=AttackProfileInput(
                        dice=1, strength=0, abilities=("charge",)
                    ),
                    short=AttackProfileInput(dice=0, strength=0),
                    long=AttackProfileInput(dice=0, strength=0),
                ),
            )
        )


def test_shield_fist_input_has_the_same_cost_as_canonical_stats() -> None:
    canonical = calculate_unit_quote(
        unit_input(
            defense=4,
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=1),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            ),
        )
    )
    shield_fist = calculate_unit_quote(
        unit_input(
            defense=1,
            shield_fist_enabled=True,
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=2),
                short=AttackProfileInput(dice=0, strength=3),
                long=AttackProfileInput(dice=0, strength=3),
            ),
        )
    )

    assert shield_fist == canonical


def test_deadly_uses_multiplier_four() -> None:
    quote = calculate_unit_quote(
        unit_input(
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=0, abilities=("deadly",)),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            )
        )
    )

    assert quote.profiles[0].ability_multiplier == Decimal("4")
    assert quote.profiles[0].cost_per_model == Decimal("12.0")
    assert quote.weapon_cost == Decimal("24.0")


def test_profile_costs_and_extra_maximum_follow_hotfix() -> None:
    quote = calculate_unit_quote(
        unit_input(
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=0),
                short=AttackProfileInput(dice=1, strength=0),
                long=AttackProfileInput(dice=1, strength=0),
            )
        )
    )

    assert [profile.cost_per_model for profile in quote.profiles] == [
        Decimal("3.0"), Decimal("3.6"), Decimal("6.0"),
    ]
    assert quote.weapon_cost == Decimal("18.6")


@pytest.mark.parametrize(
    ("range_slug", "expected"),
    (("melee", "6.0"), ("short", "7.2"), ("long", "12.0")),
)
def test_one_active_profile_is_counted_twice(
    range_slug: str, expected: str
) -> None:
    profiles = {
        slug: AttackProfileInput(dice=int(slug == range_slug), strength=0)
        for slug in ("melee", "short", "long")
    }

    quote = calculate_unit_quote(
        unit_input(profiles=AttackProfilesInput.model_validate(profiles))
    )

    assert quote.weapon_cost == Decimal(expected)


def test_tied_maximum_is_added_once_and_no_profiles_cost_zero() -> None:
    tied = calculate_unit_quote(
        unit_input(
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=2, strength=0),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=1, strength=0),
            )
        )
    )
    empty = calculate_unit_quote(
        unit_input(
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=0, strength=0),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            )
        )
    )

    assert tied.weapon_cost == Decimal("18.0")
    assert empty.weapon_cost == Decimal("0.0")


def test_charge_and_prepared_only_affect_their_ranges() -> None:
    quote = calculate_unit_quote(
        unit_input(
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(
                    dice=1, strength=0, abilities=("charge",)
                ),
                short=AttackProfileInput(
                    dice=1, strength=0, abilities=("prepared",)
                ),
                long=AttackProfileInput(
                    dice=1, strength=0, abilities=("prepared",)
                ),
            ),
        )
    )

    assert [item.ability_multiplier for item in quote.profiles] == [
        Decimal("1.4"), Decimal("1.4"), Decimal("1.4"),
    ]


def test_encirclement_and_single_use_multiply_weapon_costs() -> None:
    quote = calculate_unit_quote(
        unit_input(
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(
                    dice=1,
                    strength=0,
                    abilities=("encirclement", "single-use"),
                ),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            )
        )
    )

    assert quote.profiles[0].ability_multiplier == Decimal("0.56")


def test_order_is_ten_percent_of_base() -> None:
    quote = calculate_unit_quote(
        unit_input(special_abilities=(SpecialAbilityInput(slug="order"),))
    )
    assert quote.order_cost == quote.base_cost * Decimal("0.1")


def test_aura_cost_is_raw_delta_with_minimum_plus_one_equivalent() -> None:
    quote = calculate_unit_quote(
        unit_input(
            special_abilities=(SpecialAbilityInput(slug="aura", target_slug="agile"),)
        )
    )

    assert quote.aura_cost == Decimal("2.48")


def test_aura_can_grant_a_weapon_ability_to_compatible_profiles() -> None:
    quote = calculate_unit_quote(
        unit_input(
            special_abilities=(
                SpecialAbilityInput(slug="aura", target_slug="double"),
            )
        )
    )

    assert quote.aura_cost == Decimal("3.00")


def test_aura_recomputes_which_profile_is_most_expensive() -> None:
    quote = calculate_unit_quote(
        unit_input(
            special_abilities=(
                SpecialAbilityInput(slug="aura", target_slug="prepared"),
            ),
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=2, strength=0),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=1, strength=0),
            ),
        )
    )

    assert quote.aura_cost == Decimal("4.80")


def test_aura_weapon_range_restrictions_are_respected() -> None:
    quote = calculate_unit_quote(
        unit_input(
            special_abilities=(
                SpecialAbilityInput(slug="aura", target_slug="prepared"),
            ),
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=0),
                short=AttackProfileInput(dice=1, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            ),
        )
    )

    assert quote.aura_cost == Decimal("2.88")


@pytest.mark.parametrize("target_slug", ["airplane", "reload", "single-use"])
def test_non_aura_eligible_ability_is_rejected(target_slug: str) -> None:
    with pytest.raises(QuoteValidationError, match="not a valid Aura target"):
        calculate_unit_quote(
            unit_input(
                special_abilities=(
                    SpecialAbilityInput(slug="aura", target_slug=target_slug),
                )
            )
        )


def test_special_target_contract_comes_from_ruleset() -> None:
    with pytest.raises(QuoteValidationError, match="requires target_slug"):
        calculate_unit_quote(
            unit_input(special_abilities=(SpecialAbilityInput(slug="aura"),))
        )

    with pytest.raises(QuoteValidationError, match="does not accept target_slug"):
        calculate_unit_quote(
            unit_input(
                special_abilities=(
                    SpecialAbilityInput(slug="order", target_slug="agile"),
                )
            )
        )


def test_custom_stats_require_bounded_integer_values() -> None:
    accepted = calculate_unit_quote(
        unit_input(
            defense=Decimal("6"),
            toughness=Decimal("99"),
            custom_stats_enabled=True,
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=Decimal("4")),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            ),
        )
    )
    assert accepted.profiles[0].strength_multiplier > 0

    with pytest.raises(QuoteValidationError, match="strength must be between -1 and 4"):
        calculate_unit_quote(
            unit_input(
                custom_stats_enabled=True,
                profiles=AttackProfilesInput(
                    melee=AttackProfileInput(dice=1, strength=20),
                    short=AttackProfileInput(dice=0, strength=0),
                    long=AttackProfileInput(dice=0, strength=0),
                ),
            )
        )

    with pytest.raises(QuoteValidationError, match="defense must be an integer"):
        calculate_unit_quote(
            unit_input(defense=Decimal("3.5"), custom_stats_enabled=True)
        )


def test_standard_mode_rejects_custom_stats() -> None:
    with pytest.raises(QuoteValidationError, match="Zbroja"):
        calculate_unit_quote(unit_input(defense=Decimal("3.5")))


def test_unit_name_is_trimmed_and_bounded() -> None:
    assert unit_input(name="  Straż  ").name == "Straż"
    with pytest.raises(ValueError):
        unit_input(name="   ")
    with pytest.raises(ValueError):
        unit_input(name="x" * 121)
