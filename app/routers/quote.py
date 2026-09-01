"""Publiczny, bezstanowy endpoint wyceny i manifest UI OPOS."""

from fastapi import APIRouter, HTTPException

from ..config import OPOS_RULESET_VERSION
from ..services.opos_rules import (
    QuoteValidationError,
    UnitQuoteInput,
    calculate_unit_quote,
    display_stat_value,
    load_opos_ruleset,
    stat_label,
)


router = APIRouter(tags=["rules"])


def _displayed_stats(ruleset, shield_fist_enabled: bool) -> dict[str, list[object]]:
    return {
        stat_name: [
            display_stat_value(
                stat_name,
                value,
                shield_fist_enabled=shield_fist_enabled,
            )
            for value in getattr(ruleset.standard_stats, stat_name)
        ]
        for stat_name in ("defense", "toughness", "strength")
    }


def _displayed_custom_limits(ruleset, shield_fist_enabled: bool) -> dict[str, object] | None:
    if ruleset.custom_stats is None:
        return None
    result: dict[str, object] = {}
    for stat_name in ("defense", "toughness", "strength"):
        limits = getattr(ruleset.custom_stats, stat_name)
        values = [
            display_stat_value(
                stat_name,
                value,
                shield_fist_enabled=shield_fist_enabled,
            )
            for value in (limits.minimum, limits.maximum)
        ]
        result[stat_name] = {
            "minimum": min(values),
            "maximum": max(values),
            "integer_only": limits.integer_only,
        }
    return result


@router.get("/ruleset")
def ruleset_manifest(shield_fist_enabled: bool = False) -> dict[str, object]:
    ruleset = load_opos_ruleset(OPOS_RULESET_VERSION)
    return {
        "version": ruleset.version,
        "standard_stats": _displayed_stats(ruleset, shield_fist_enabled),
        "custom_stats": _displayed_custom_limits(ruleset, shield_fist_enabled),
        "stat_labels": {
            stat_name: stat_label(
                stat_name, shield_fist_enabled=shield_fist_enabled
            )
            for stat_name in ("defense", "toughness", "strength")
        },
        "shield_fist_enabled": shield_fist_enabled,
        "stat_descriptions": ruleset.stat_descriptions,
        "ranges": {
            slug: definition.model_dump(mode="json")
            for slug, definition in ruleset.ranges.items()
        },
        "stat_icons": ruleset.stat_icons,
        "abilities": [item.model_dump(mode="json") for item in ruleset.abilities],
    }


@router.post("/quote")
def quote_unit(payload: UnitQuoteInput) -> dict[str, object]:
    try:
        quote = calculate_unit_quote(payload, ruleset_version=OPOS_RULESET_VERSION)
    except QuoteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return quote.model_dump(mode="json")
