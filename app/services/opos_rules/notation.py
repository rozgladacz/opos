"""Kanoniczna konwersja i formatowanie notacji Tarcza/Pięść."""

from __future__ import annotations

from decimal import Decimal


THREE = Decimal("3")


def canonical_stat_value(
    stat_name: str, value: Decimal, *, shield_fist_enabled: bool
) -> Decimal:
    """Convert an editor value into the canonical Zbroja/Siła representation."""
    if not shield_fist_enabled:
        return value
    if stat_name == "defense":
        return value + THREE
    if stat_name == "strength":
        return THREE - value
    return value


def display_stat_value(
    stat_name: str, value: object, *, shield_fist_enabled: bool
) -> Decimal:
    """Convert a canonical stored value into the active editor representation."""
    number = Decimal(str(value))
    if not shield_fist_enabled:
        return number
    if stat_name == "defense":
        return number - THREE
    if stat_name == "strength":
        return THREE - number
    return number


def display_number(value: object) -> str:
    number = Decimal(str(value))
    return format(number.normalize(), "f")


def format_stat_value(
    stat_name: str, value: object, *, shield_fist_enabled: bool
) -> str:
    """Format a canonical value for lists and cards."""
    displayed = display_stat_value(
        stat_name, value, shield_fist_enabled=shield_fist_enabled
    )
    text = display_number(displayed)
    if not shield_fist_enabled:
        return text
    if stat_name == "defense":
        return text if displayed < 0 else f"+{text}"
    if stat_name == "strength":
        return f"{text}+"
    return text


def stat_label(stat_name: str, *, shield_fist_enabled: bool) -> str:
    labels = {
        "defense": "Tarcza" if shield_fist_enabled else "Zbroja",
        "strength": "Pięść" if shield_fist_enabled else "Siła",
        "toughness": "Życie",
    }
    return labels[stat_name]
