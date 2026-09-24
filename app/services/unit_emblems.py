"""Presentation-only unit emblems; independent of rules and point costs."""

UNIT_EMBLEMS = {
    "sword": "Miecz",
    "fist": "Pięść",
    "shield": "Tarcza",
    "axe": "Topór",
    "helmet": "Hełm",
    "wing": "Skrzydło",
    "horse": "Koń",
    "bow": "Łuk",
    "crossbow": "Kusza",
    "rifle": "Karabin",
    "pistol": "Pistolet",
    "cannon": "Działo",
    "tank": "Czołg",
    "mech": "Dwunożny mech",
    "jaws": "Paszcza",
    "crown": "Korona",
    "grenade": "Granat",
    "banner": "Sztandar",
    "medical": "Krzyż medyczny",
    "parachute": "Spadochron",
    "wand": "Magiczna różdżka",
    "flame": "Płomień",
    "drop": "Kropla",
    "spyglass": "Luneta",
    "hammer": "Młot",
    "radio": "Radio",
    "note": "Nuta",
    "epaulette": "Pagon",
}


def validate_emblem(value: str | None) -> str | None:
    if value is not None and value not in UNIT_EMBLEMS:
        raise ValueError("Nieznany symbol oddziału")
    return value
