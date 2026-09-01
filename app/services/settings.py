"""Persystentne ustawienia aplikacji zapisywane w data/settings.json.

Ustawienia przeżywają restart kontenera (data/ jest na wolumenie).
ENV var jest zawsze nadrzędna nad ustawieniem z pliku.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ..config import DATA_DIR

logger = logging.getLogger(__name__)

_SETTINGS_FILE = DATA_DIR / "settings.json"
_DEFAULTS: dict = {
    "registration_open": True,
}


def _read() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        logger.warning("Nie udało się odczytać %s — używam wartości domyślnych.", _SETTINGS_FILE)
        return {}


def _write(data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = _SETTINGS_FILE.with_name(_SETTINGS_FILE.stem + ".tmp.json")
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(tmp, _SETTINGS_FILE)  # atomowy na Linux
    except PermissionError:
        # Windows: os.replace może wymagać że plik docelowy nie jest zajęty.
        # Fallback: bezpośredni zapis (nie atomowy, ale akceptowalny dla tej skali).
        tmp.unlink(missing_ok=True)
        _SETTINGS_FILE.write_text(payload, encoding="utf-8")


def get_registration_open() -> bool:
    """Czy rejestracja publiczna jest aktywna.

    Kolejność priorytetów:
    1. Zmienna środowiskowa REGISTRATION_OPEN (true/false/1/0/yes/no)
    2. Ustawienie w data/settings.json
    3. Domyślna wartość True
    """
    env = os.getenv("REGISTRATION_OPEN", "").strip().lower()
    if env in {"true", "1", "yes"}:
        return True
    if env in {"false", "0", "no"}:
        return False
    return _read().get("registration_open", _DEFAULTS["registration_open"])


def set_registration_open(value: bool) -> None:
    """Zmień stan rejestracji i zapisz do data/settings.json."""
    data = _read()
    data["registration_open"] = value
    _write(data)
