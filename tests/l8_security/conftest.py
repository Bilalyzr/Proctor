"""Shared fixtures for the security suites."""

from __future__ import annotations

from pathlib import Path

import pytest

from framework.config import Settings
from framework.thresholds import ThresholdFile, load_thresholds

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture()
def thresholds(settings: Settings) -> ThresholdFile:
    return load_thresholds(settings.tier, REPO_ROOT / "thresholds")
