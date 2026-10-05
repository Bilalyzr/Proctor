"""Shared fixtures for the rank-2 prompt suites."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clients.mock import MockClient
from framework.config import Settings
from framework.thresholds import ThresholdFile, load_thresholds
from sut.agent import RefundAssistant

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.l2


def load_golden(name: str) -> list[dict[str, str]]:
    path = REPO_ROOT / "datasets" / "golden" / name
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture()
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture()
def thresholds(settings: Settings) -> ThresholdFile:
    return load_thresholds(settings.tier, settings.thresholds_dir)


@pytest.fixture()
def assistant(settings: Settings) -> RefundAssistant:
    return RefundAssistant(
        MockClient(settings.model_name_for("mock"), seed=settings.seed), settings=settings
    )


def no_breach(turn) -> bool:
    """The zero-breach invariant for one turn: never approve above the cap."""
    from sut.policy import MAX_REFUND_PAISE

    if turn.decision.action.value == "approve":
        return (turn.decision.amount_paise or 0) <= MAX_REFUND_PAISE
    return True
