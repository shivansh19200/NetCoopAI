"""Shared thresholds and deterministic diagnosis scoring."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "thresholds.yaml"


@lru_cache(maxsize=1)
def config() -> dict:
    """Load the scoring configuration once per process."""
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def threshold(metric: str, device_type: str = "device", fallback: float = 0) -> float:
    """Return the device-specific threshold, then the shared default."""
    settings = config()
    return settings.get("device_types", {}).get(str(device_type).lower(), {}).get(
        metric, settings.get("defaults", {}).get(metric, fallback)
    )


def cause_priority(cause: str) -> int:
    return config().get("cause_priority", {}).get(cause, 0)


def setting(name: str, fallback: float = 0) -> float:
    """Read a scoring setting by dotted path, such as ``scoring.maximum``."""
    value = config()
    for part in name.split("."):
        if not isinstance(value, dict) or part not in value:
            return fallback
        value = value[part]
    return value


def candidate_score(families: int, signals: int) -> float:
    settings = config().get("scoring", {})
    family_weight = settings.get("family_weight", 0.36)
    signal_weight = settings.get("additional_signal_weight", 0.05)
    return min(settings.get("maximum", 0.95),
               family_weight * min(settings.get("max_families", 3), families)
               + signal_weight * min(settings.get("max_additional_signals", 3), max(0, signals - 1)))
