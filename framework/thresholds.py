"""Versioned threshold loading (GOV-2).

Reads ``thresholds/<tier>.yaml`` into a typed model; the file's SHA-256 is
embedded in run manifests and sign-off records so a gate decision can always be
reproduced against the exact thresholds that produced it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

KNOWN_LAYERS = ("l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9")
KNOWN_TIERS = ("critical", "high", "standard")


class ThresholdFile(BaseModel):
    """One risk tier's gate values.

    Values are numeric; occasional non-numeric settings (e.g. ``gate_mode``)
    are stored as strings alongside them.
    """

    version: int
    tier: str
    layers: dict[str, dict[str, float | str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> ThresholdFile:
        if self.tier not in KNOWN_TIERS:
            msg = f"unknown tier {self.tier!r}; expected one of {KNOWN_TIERS}"
            raise ValueError(msg)
        unknown = set(self.layers) - set(KNOWN_LAYERS)
        if unknown:
            msg = f"unknown layers {sorted(unknown)}; expected subsets of {KNOWN_LAYERS}"
            raise ValueError(msg)
        return self

    def gate_value(self, layer: str, key: str, default: float | None = None) -> float:
        """Fetch one gate value; missing keys fall back to ``default``."""
        try:
            return float(self.layers[layer][key])
        except KeyError:
            if default is not None:
                return default
            msg = f"thresholds for tier {self.tier!r} lack {layer}.{key}"
            raise KeyError(msg) from None


def load_thresholds(tier: str, thresholds_dir: str | Path = "thresholds") -> ThresholdFile:
    """Load and validate ``thresholds/<tier>.yaml``."""
    if tier not in KNOWN_TIERS:
        msg = f"unknown tier {tier!r}; expected one of {KNOWN_TIERS}"
        raise ValueError(msg)
    path = Path(thresholds_dir) / f"{tier}.yaml"
    if not path.exists():
        msg = f"threshold file missing: {path}"
        raise FileNotFoundError(msg)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ThresholdFile.model_validate(raw)


def available_tiers(thresholds_dir: str | Path = "thresholds") -> list[str]:
    """Tiers that actually have a file on disk."""
    directory = Path(thresholds_dir)
    return sorted(p.stem for p in directory.glob("*.yaml") if p.stem in KNOWN_TIERS)
