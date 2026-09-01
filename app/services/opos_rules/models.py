"""Zwalidowany model jedynego wykonywalnego rulesetu OPOS."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_FROZEN = ConfigDict(frozen=True, extra="forbid")
AbilityCategory = Literal["passive", "special", "weapon"]
RangeSlug = Literal["melee", "short", "long"]


class RulesetSources(BaseModel):
    model_config = _FROZEN

    normative: str
    published: str


class StandardStats(BaseModel):
    model_config = _FROZEN

    defense: tuple[Decimal, ...]
    toughness: tuple[Decimal, ...]
    strength: tuple[Decimal, ...]


class StatLimitDefinition(BaseModel):
    model_config = _FROZEN

    minimum: Decimal
    maximum: Decimal
    integer_only: bool = True

    @model_validator(mode="after")
    def validate_bounds(self) -> "StatLimitDefinition":
        if self.minimum > self.maximum:
            raise ValueError("Stat minimum must not exceed maximum")
        return self


class CustomStatsDefinition(BaseModel):
    model_config = _FROZEN

    defense: StatLimitDefinition
    toughness: StatLimitDefinition
    strength: StatLimitDefinition


class FormulaDefinition(BaseModel):
    model_config = _FROZEN

    base_constant: Decimal
    defense_quadratic: Decimal
    defense_linear: Decimal
    defense_constant: Decimal
    weapon_factor: Decimal
    strength_quadratic: Decimal
    strength_linear: Decimal
    strength_constant: Decimal
    toughness_modifier_per_point: Decimal
    aura_minimum_ability_cost: Decimal


class RangeDefinition(BaseModel):
    model_config = _FROZEN

    name: str
    multiplier: Decimal = Field(gt=0)
    icon: str


class ConditionalAbilityCost(BaseModel):
    model_config = _FROZEN

    any_of: tuple[str, ...]
    delta: Decimal

    @model_validator(mode="after")
    def validate_condition(self) -> "ConditionalAbilityCost":
        if not self.any_of:
            raise ValueError("Conditional ability cost requires any_of")
        return self


class AbilityEffects(BaseModel):
    model_config = _FROZEN

    ability_cost_delta: Decimal = Decimal("0")
    toughness_multiplier: Decimal = Decimal("1")
    toughness_flat_bonus: Decimal = Decimal("0")
    defense_bonus: Decimal = Decimal("0")
    strength_bonus: Decimal = Decimal("0")
    base_cost_fraction: Decimal = Decimal("0")
    weapon_multiplier: Decimal = Decimal("1")
    profile_multipliers: dict[RangeSlug, Decimal] = Field(default_factory=dict)
    conditional_ability_costs: tuple[ConditionalAbilityCost, ...] = ()
    small_battle_toughness_flat_bonus: Decimal | None = None
    small_battle_weapon_multiplier: Decimal | None = None


class AbilityDefinition(BaseModel):
    model_config = _FROZEN

    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    name: str
    category: AbilityCategory
    icon: str
    description: str
    small_battle_description: str | None = None
    aura_eligible: bool = False
    requires_target: bool = False
    allowed_ranges: tuple[RangeSlug, ...] = ("melee", "short", "long")
    incompatible_with: tuple[str, ...] = ()
    effects: AbilityEffects = Field(default_factory=AbilityEffects)

    @model_validator(mode="after")
    def validate_category_contract(self) -> "AbilityDefinition":
        if self.aura_eligible and self.category not in {"passive", "weapon"}:
            raise ValueError("Only passive and weapon abilities can be aura targets")
        if self.requires_target and self.category != "special":
            raise ValueError("Only special abilities can require a target")
        return self


class OposRuleset(BaseModel):
    model_config = _FROZEN

    version: str
    game: Literal["OPOS"]
    sources: RulesetSources
    standard_stats: StandardStats
    custom_stats: CustomStatsDefinition | None = None
    stat_descriptions: dict[str, tuple[str, ...]]
    formula: FormulaDefinition
    ranges: dict[RangeSlug, RangeDefinition]
    stat_icons: dict[str, str]
    abilities: tuple[AbilityDefinition, ...]

    @model_validator(mode="after")
    def validate_manifest(self) -> "OposRuleset":
        if set(self.ranges) != {"melee", "short", "long"}:
            raise ValueError("Ruleset must define melee, short and long ranges")
        slugs = [ability.slug for ability in self.abilities]
        if len(slugs) != len(set(slugs)):
            raise ValueError("Ability slugs must be unique")
        required_stats = {"defense", "toughness", "strength", "dice", "activation"}
        if not required_stats.issubset(self.stat_icons):
            raise ValueError("Ruleset stat_icons are incomplete")
        for stat_name in ("defense", "toughness", "strength"):
            values = getattr(self.standard_stats, stat_name)
            if len(self.stat_descriptions.get(stat_name, ())) != len(values):
                raise ValueError(f"Descriptions for {stat_name} are incomplete")
        known = set(slugs)
        for ability in self.abilities:
            invalid = set(ability.incompatible_with) - known
            if invalid:
                raise ValueError(
                    f"Unknown incompatible abilities for {ability.slug}: {sorted(invalid)}"
                )
            if ability.slug in ability.incompatible_with:
                raise ValueError(f"Ability {ability.slug} cannot conflict with itself")
            for conditional in ability.effects.conditional_ability_costs:
                invalid_conditions = set(conditional.any_of) - known
                if invalid_conditions:
                    raise ValueError(
                        f"Unknown conditional abilities for {ability.slug}: "
                        f"{sorted(invalid_conditions)}"
                    )
        return self

    @property
    def abilities_by_slug(self) -> dict[str, AbilityDefinition]:
        return {ability.slug: ability for ability in self.abilities}

    def abilities_of(self, category: AbilityCategory) -> tuple[AbilityDefinition, ...]:
        return tuple(item for item in self.abilities if item.category == category)

    @property
    def aura_targets(self) -> tuple[AbilityDefinition, ...]:
        return tuple(item for item in self.abilities if item.aura_eligible)
