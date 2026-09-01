"""Stateless OPOS quote engine driven exclusively by the YAML ruleset."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .loader import load_opos_ruleset
from .models import AbilityDefinition, OposRuleset, RangeSlug
from .notation import canonical_stat_value


_INPUT_CONFIG = ConfigDict(extra="forbid")
_OUTPUT_CONFIG = ConfigDict(frozen=True, extra="forbid")
ZERO = Decimal("0")
ONE = Decimal("1")


def scale_points(points: int | Decimal | None, points_scale: int) -> int | None:
    """Scale a stored base-points value for display using half-up rounding."""
    if points is None:
        return None
    if points_scale < 1:
        raise ValueError("Points scale must be positive")
    return int(
        (Decimal(points) / Decimal(points_scale)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def scale_entry_cost(
    unit_cost: int | Decimal, unit_copies: int, points_scale: int
) -> int:
    """Scale one stored unit cost before applying the number of copies."""
    scaled_unit_cost = scale_points(unit_cost, points_scale)
    assert scaled_unit_cost is not None
    return scaled_unit_cost * unit_copies


class AttackProfileInput(BaseModel):
    model_config = _INPUT_CONFIG

    dice: int = Field(ge=0, le=999)
    strength: Decimal
    abilities: tuple[str, ...] = ()


class AttackProfilesInput(BaseModel):
    model_config = _INPUT_CONFIG

    melee: AttackProfileInput
    short: AttackProfileInput
    long: AttackProfileInput

    def items(self) -> tuple[tuple[RangeSlug, AttackProfileInput], ...]:
        return (
            ("melee", self.melee),
            ("short", self.short),
            ("long", self.long),
        )


class SpecialAbilityInput(BaseModel):
    model_config = _INPUT_CONFIG

    slug: str
    target_slug: str | None = None


class UnitQuoteInput(BaseModel):
    model_config = _INPUT_CONFIG

    name: str = Field(default="Oddział", min_length=1, max_length=120)
    models_per_unit: int = Field(ge=1, le=999)
    unit_copies: int = Field(default=1, ge=1, le=999)
    defense: Decimal
    toughness: Decimal = Field(gt=0)
    passive_abilities: tuple[str, ...] = ()
    special_abilities: tuple[SpecialAbilityInput, ...] = ()
    profiles: AttackProfilesInput
    custom_stats_enabled: bool = False
    points_scale: int = Field(default=1, ge=1, le=1_000_000)
    small_battle_enabled: bool = False
    shield_fist_enabled: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Name cannot be empty")
        return name


class ProfileQuote(BaseModel):
    model_config = _OUTPUT_CONFIG

    range: RangeSlug
    active: bool
    dice: int
    effective_strength: Decimal
    strength_multiplier: Decimal
    ability_multiplier: Decimal
    cost_per_model: Decimal
    cost_all_models: Decimal


class QuoteBreakdown(BaseModel):
    model_config = _OUTPUT_CONFIG

    ruleset_version: str
    toughness_sum: Decimal
    effective_defense: Decimal
    defense_multiplier: Decimal
    ability_cost_modifier: Decimal
    base_cost: Decimal
    weapon_cost: Decimal
    order_cost: Decimal
    aura_cost: Decimal
    toughness_modifier: Decimal
    raw_unit_cost: Decimal
    points_scale: Decimal
    unscaled_unit_cost: Decimal
    rounded_unit_cost: Decimal
    unit_copies: int
    entry_cost: Decimal
    profiles: tuple[ProfileQuote, ...]


class QuoteValidationError(ValueError):
    """Raised when a syntactically valid quote violates the active ruleset."""


def canonicalize_unit_input(request: UnitQuoteInput) -> UnitQuoteInput:
    """Return the canonical snapshot/quote representation of editor input."""
    if not request.shield_fist_enabled:
        return request
    profiles = {
        range_slug: profile.model_copy(
            update={
                "strength": canonical_stat_value(
                    "strength",
                    profile.strength,
                    shield_fist_enabled=True,
                )
            }
        )
        for range_slug, profile in request.profiles.items()
    }
    return request.model_copy(
        update={
            "defense": canonical_stat_value(
                "defense", request.defense, shield_fist_enabled=True
            ),
            "profiles": request.profiles.model_copy(update=profiles),
            "shield_fist_enabled": False,
        }
    )


def _ability_map(ruleset: OposRuleset) -> dict[str, AbilityDefinition]:
    return ruleset.abilities_by_slug


def _unique(values: tuple[str, ...], field: str) -> None:
    if len(values) != len(set(values)):
        raise QuoteValidationError(f"{field} contains duplicates")


def _selected_ability_slugs(request: UnitQuoteInput) -> set[str]:
    selected = set(request.passive_abilities)
    selected.update(item.slug for item in request.special_abilities)
    for _, profile in request.profiles.items():
        selected.update(profile.abilities)
    return selected


def _validate_request(request: UnitQuoteInput, ruleset: OposRuleset) -> None:
    abilities = _ability_map(ruleset)
    _unique(request.passive_abilities, "passive_abilities")
    for slug in request.passive_abilities:
        if slug not in abilities or abilities[slug].category != "passive":
            raise QuoteValidationError(f"Unknown passive ability: {slug}")

    special_keys = tuple(
        f"{item.slug}:{item.target_slug or ''}" for item in request.special_abilities
    )
    _unique(special_keys, "special_abilities")
    for item in request.special_abilities:
        definition = abilities.get(item.slug)
        if definition is None or definition.category != "special":
            raise QuoteValidationError(f"Unknown special ability: {item.slug}")
        if definition.requires_target and not item.target_slug:
            raise QuoteValidationError(f"{definition.name} requires target_slug")
        if not definition.requires_target and item.target_slug is not None:
            raise QuoteValidationError(f"{definition.name} does not accept target_slug")
        if definition.requires_target:
            target = abilities.get(item.target_slug or "")
            if target is None or not target.aura_eligible:
                raise QuoteValidationError(f"Ability is not a valid Aura target: {item.target_slug}")

    if request.custom_stats_enabled and ruleset.custom_stats is not None:
        values = {
            "defense": (request.defense,),
            "toughness": (request.toughness,),
            "strength": tuple(profile.strength for _, profile in request.profiles.items()),
        }
        for stat_name, stat_values in values.items():
            limits = getattr(ruleset.custom_stats, stat_name)
            for value in stat_values:
                if limits.integer_only and value != value.to_integral_value():
                    raise QuoteValidationError(
                        f"{stat_name} must be an integer in custom stats mode"
                    )
                if value < limits.minimum or value > limits.maximum:
                    raise QuoteValidationError(
                        f"{stat_name} must be between {limits.minimum} and {limits.maximum}"
                    )
    elif request.defense <= ZERO:
        raise QuoteValidationError("Zbroja must be positive")

    if not request.custom_stats_enabled:
        standard = ruleset.standard_stats
        if request.defense not in standard.defense:
            raise QuoteValidationError("Zbroja is outside the standard list")
        allowed_toughness = tuple(
            value * (Decimal("2") if request.small_battle_enabled else ONE)
            for value in standard.toughness
        )
        if request.toughness not in allowed_toughness:
            raise QuoteValidationError("Życie is outside the standard list")

    formula = ruleset.formula
    passive_defs = tuple(abilities[slug] for slug in request.passive_abilities)
    strength_bonus = sum((item.effects.strength_bonus for item in passive_defs), ZERO)
    for range_slug, profile in request.profiles.items():
        _unique(profile.abilities, f"profiles.{range_slug}.abilities")
        if not request.custom_stats_enabled and profile.strength not in ruleset.standard_stats.strength:
            raise QuoteValidationError(f"Strength for {range_slug} is outside the standard list")
        effective_strength = profile.strength + strength_bonus
        multiplier = (
            formula.strength_quadratic * effective_strength * effective_strength
            + formula.strength_linear * effective_strength
            + formula.strength_constant
        )
        if multiplier <= ZERO:
            raise QuoteValidationError(f"Strength multiplier for {range_slug} must be positive")
        for slug in profile.abilities:
            definition = abilities.get(slug)
            if definition is None or definition.category != "weapon":
                raise QuoteValidationError(f"Unknown weapon ability: {slug}")
            if range_slug not in definition.allowed_ranges:
                raise QuoteValidationError(f"{definition.name} is not allowed at {range_slug} range")

    selected = _selected_ability_slugs(request)
    for slug in sorted(selected):
        for other in abilities[slug].incompatible_with:
            if other in selected:
                raise QuoteValidationError(
                    f"Zdolności {abilities[slug].name} i {abilities[other].name} "
                    "wzajemnie się wykluczają"
                )


def _passive_effects(
    passive_slugs: tuple[str, ...], ruleset: OposRuleset
) -> tuple[AbilityDefinition, ...]:
    abilities = _ability_map(ruleset)
    return tuple(abilities[slug] for slug in passive_slugs)


def _toughness_sum(
    request: UnitQuoteInput,
    passive_defs: tuple[AbilityDefinition, ...],
    special_defs: tuple[AbilityDefinition, ...],
) -> Decimal:
    value = Decimal(request.models_per_unit) * request.toughness
    for ability in passive_defs:
        value *= ability.effects.toughness_multiplier
    for ability in special_defs:
        bonus = ability.effects.toughness_flat_bonus
        if (
            request.small_battle_enabled
            and ability.effects.small_battle_toughness_flat_bonus is not None
        ):
            bonus = ability.effects.small_battle_toughness_flat_bonus
        value += bonus
    return value


def _effective_defense(
    defense: Decimal, passive_defs: tuple[AbilityDefinition, ...]
) -> Decimal:
    return defense + sum((item.effects.defense_bonus for item in passive_defs), ZERO)


def _defense_multiplier(value: Decimal, ruleset: OposRuleset) -> Decimal:
    formula = ruleset.formula
    return (
        formula.defense_quadratic * value * value
        + formula.defense_linear * value
        + formula.defense_constant
    )


def _base_cost(
    request: UnitQuoteInput,
    passive_defs: tuple[AbilityDefinition, ...],
    special_defs: tuple[AbilityDefinition, ...],
    ruleset: OposRuleset,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    formula = ruleset.formula
    toughness_sum = _toughness_sum(request, passive_defs, special_defs)
    effective_defense = _effective_defense(request.defense, passive_defs)
    defense_multiplier = _defense_multiplier(effective_defense, ruleset)
    ability_delta = sum((item.effects.ability_cost_delta for item in passive_defs), ZERO)
    ability_delta += sum((item.effects.ability_cost_delta for item in special_defs), ZERO)
    selected = _selected_ability_slugs(request)
    for ability in (*passive_defs, *special_defs):
        for conditional in ability.effects.conditional_ability_costs:
            if selected.intersection(conditional.any_of):
                ability_delta += conditional.delta
    base = (formula.base_constant + ability_delta) * defense_multiplier * toughness_sum
    return base, toughness_sum, effective_defense, ability_delta


def _profile_costs(
    request: UnitQuoteInput,
    passive_defs: tuple[AbilityDefinition, ...],
    ruleset: OposRuleset,
) -> tuple[Decimal, tuple[ProfileQuote, ...]]:
    formula = ruleset.formula
    abilities = _ability_map(ruleset)
    strength_bonus = sum((item.effects.strength_bonus for item in passive_defs), ZERO)
    breakdown: list[ProfileQuote] = []
    total = ZERO
    most_expensive = ZERO
    for range_slug, profile in request.profiles.items():
        effective_strength = profile.strength + strength_bonus
        strength_multiplier = (
            formula.strength_quadratic * effective_strength * effective_strength
            + formula.strength_linear * effective_strength
            + formula.strength_constant
        )
        ability_multiplier = ONE
        for passive in passive_defs:
            ability_multiplier *= passive.effects.profile_multipliers.get(range_slug, ONE)
        for slug in profile.abilities:
            effects = abilities[slug].effects
            multiplier = effects.weapon_multiplier
            if request.small_battle_enabled and effects.small_battle_weapon_multiplier is not None:
                multiplier = effects.small_battle_weapon_multiplier
            ability_multiplier *= multiplier
        per_model = (
            Decimal(profile.dice)
            * formula.weapon_factor
            * ruleset.ranges[range_slug].multiplier
            * strength_multiplier
            * ability_multiplier
        )
        all_models = per_model * Decimal(request.models_per_unit)
        total += all_models
        if profile.dice > 0:
            most_expensive = max(most_expensive, all_models)
        breakdown.append(
            ProfileQuote(
                range=range_slug,
                active=profile.dice > 0,
                dice=profile.dice,
                effective_strength=effective_strength,
                strength_multiplier=strength_multiplier,
                ability_multiplier=ability_multiplier,
                cost_per_model=per_model,
                cost_all_models=all_models,
            )
        )
    return total + most_expensive, tuple(breakdown)


def _core_cost(
    request: UnitQuoteInput,
    passive_slugs: tuple[str, ...],
    special_defs: tuple[AbilityDefinition, ...],
    ruleset: OposRuleset,
) -> Decimal:
    passive_defs = _passive_effects(passive_slugs, ruleset)
    base, _, _, _ = _base_cost(request, passive_defs, special_defs, ruleset)
    weapons, _ = _profile_costs(request, passive_defs, ruleset)
    return base + weapons


def _with_weapon_ability(
    request: UnitQuoteInput, definition: AbilityDefinition
) -> UnitQuoteInput:
    """Apply an Aura weapon target to every compatible attack profile."""
    updates: dict[str, AttackProfileInput] = {}
    for range_slug, profile in request.profiles.items():
        if range_slug not in definition.allowed_ranges:
            continue
        abilities = tuple(dict.fromkeys((*profile.abilities, definition.slug)))
        updates[range_slug] = profile.model_copy(update={"abilities": abilities})
    return request.model_copy(
        update={"profiles": request.profiles.model_copy(update=updates)}
    )


def calculate_unit_quote(
    request: UnitQuoteInput, *, ruleset_version: str = "v3"
) -> QuoteBreakdown:
    """Calculate one shared unit profile and its copy total without DB access."""
    request = canonicalize_unit_input(request)
    ruleset = load_opos_ruleset(ruleset_version)
    _validate_request(request, ruleset)
    abilities = _ability_map(ruleset)
    passive_defs = _passive_effects(request.passive_abilities, ruleset)
    special_defs = tuple(abilities[item.slug] for item in request.special_abilities)

    base, toughness_sum, effective_defense, ability_delta = _base_cost(
        request, passive_defs, special_defs, ruleset
    )
    defense_multiplier = _defense_multiplier(effective_defense, ruleset)
    weapon_cost, profiles = _profile_costs(request, passive_defs, ruleset)

    order_fraction = sum((item.effects.base_cost_fraction for item in special_defs), ZERO)
    order_cost = base * order_fraction

    baseline_core = base + weapon_cost
    minimum_aura = (
        ruleset.formula.aura_minimum_ability_cost
        * defense_multiplier
        * toughness_sum
    )
    aura_cost = ZERO
    for selection in request.special_abilities:
        if not abilities[selection.slug].requires_target:
            continue
        target = abilities[selection.target_slug or ""]
        if target.category == "passive":
            augmented_passives = tuple(
                dict.fromkeys((*request.passive_abilities, target.slug))
            )
            augmented_request = request
        else:
            augmented_passives = request.passive_abilities
            augmented_request = _with_weapon_ability(request, target)
        delta = (
            _core_cost(
                augmented_request,
                augmented_passives,
                special_defs,
                ruleset,
            )
            - baseline_core
        )
        aura_cost += max(delta, minimum_aura)

    toughness_modifier = ONE + ruleset.formula.toughness_modifier_per_point * request.toughness
    points_scale = Decimal(request.points_scale)
    unscaled_raw_unit_cost = (
        (base + weapon_cost + order_cost + aura_cost)
        * toughness_modifier
    )
    unscaled_unit_cost = unscaled_raw_unit_cost.quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    raw_unit_cost = unscaled_raw_unit_cost / points_scale
    rounded_unit_cost = Decimal(scale_points(unscaled_unit_cost, request.points_scale))
    entry_cost = Decimal(
        scale_entry_cost(
            unscaled_unit_cost, request.unit_copies, request.points_scale
        )
    )
    scaled_profiles = tuple(
        profile.model_copy(
            update={
                "cost_per_model": profile.cost_per_model / points_scale,
                "cost_all_models": profile.cost_all_models / points_scale,
            }
        )
        for profile in profiles
    )
    return QuoteBreakdown(
        ruleset_version=ruleset.version,
        toughness_sum=toughness_sum,
        effective_defense=effective_defense,
        defense_multiplier=defense_multiplier,
        ability_cost_modifier=ability_delta,
        base_cost=base / points_scale,
        weapon_cost=weapon_cost / points_scale,
        order_cost=order_cost / points_scale,
        aura_cost=aura_cost / points_scale,
        toughness_modifier=toughness_modifier,
        raw_unit_cost=raw_unit_cost,
        points_scale=points_scale,
        unscaled_unit_cost=unscaled_unit_cost,
        rounded_unit_cost=rounded_unit_cost,
        unit_copies=request.unit_copies,
        entry_cost=entry_cost,
        profiles=scaled_profiles,
    )
