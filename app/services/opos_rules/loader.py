"""Wczytywanie i cache zwalidowanego rulesetu OPOS."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .models import OposRuleset


RULESET_ROOT = Path(__file__).resolve().parents[2] / "rulesets" / "opos"
SUPPORTED_RULESET_VERSIONS = ("v1", "v3")


@lru_cache(maxsize=len(SUPPORTED_RULESET_VERSIONS))
def load_opos_ruleset(version: str = "v3") -> OposRuleset:
    """Return an immutable cached ruleset without database access."""
    if version not in SUPPORTED_RULESET_VERSIONS:
        raise ValueError(f"Unsupported OPOS ruleset version: {version}")
    path = RULESET_ROOT / version / "rules.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return OposRuleset.model_validate(raw)
