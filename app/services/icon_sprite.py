"""Render icons from the single OPOS SVG sprite without external ``<use>`` links."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from markupsafe import Markup

from ..paths import STATIC_DIR


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
SPRITE_PATH = Path(STATIC_DIR) / "icons" / "opos.svg"


@lru_cache(maxsize=1)
def _sprite_index() -> dict[str, ET.Element]:
    root = ET.parse(SPRITE_PATH).getroot()
    return {
        element_id: element
        for element in root.iter()
        if (element_id := element.attrib.get("id"))
    }


def _expanded_copy(element: ET.Element) -> ET.Element:
    local_name = element.tag.rsplit("}", 1)[-1]
    if local_name == "use":
        href = element.attrib.get("href") or element.attrib.get(XLINK_HREF, "")
        target = _sprite_index().get(href.removeprefix("#"))
        if target is None:
            raise ValueError(f"Unknown SVG reference: {href}")
        wrapper = ET.Element("g")
        for key, value in target.attrib.items():
            if key not in {"id", "viewBox"}:
                wrapper.set(key, value)
        for key, value in element.attrib.items():
            if key not in {"href", XLINK_HREF}:
                wrapper.set(key, value)
        for child in target:
            wrapper.append(_expanded_copy(child))
        return wrapper

    clone = ET.Element(
        local_name,
        {key: value for key, value in element.attrib.items() if key != "id"},
    )
    clone.text = element.text
    clone.tail = element.tail
    for child in element:
        clone.append(_expanded_copy(child))
    return clone


@lru_cache(maxsize=128)
def render_card_icon(icon_name: str) -> Markup:
    """Return safe inline SVG expanded from ``app/static/icons/opos.svg``."""

    symbol = _sprite_index().get(f"icon-{icon_name}")
    if symbol is None:
        raise ValueError(f"Unknown OPOS icon: {icon_name}")
    svg = ET.Element(
        "svg",
        {
            "xmlns": SVG_NAMESPACE,
            "class": "card-icon",
            "viewBox": symbol.attrib.get("viewBox", "0 0 24 24"),
            "width": "24",
            "height": "24",
            "fill": "none",
            "stroke": "currentColor",
            "stroke-width": "1.65",
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
        },
    )
    for child in symbol:
        svg.append(_expanded_copy(child))
    return Markup(ET.tostring(svg, encoding="unicode"))
