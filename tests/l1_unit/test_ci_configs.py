"""Rank-1 unit tests: CI workflow configurations (GOV-4).

Static verification that the scheduled regression exists and publishes run
artifacts - the workflow itself runs in GitHub Actions.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.l1

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _triggers(spec: dict) -> dict:
    # YAML 1.1 parses the `on` key as boolean True
    return spec.get(True) or spec.get("on") or {}


def test_nightly_regression_exists_with_schedule() -> None:
    path = WORKFLOWS / "nightly.yml"
    assert path.exists(), "GOV-4: nightly regression workflow missing"
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = _triggers(spec)
    assert "schedule" in triggers
    cron = triggers["schedule"][0]["cron"]
    assert isinstance(cron, str) and len(cron.split()) == 5  # real 5-field cron
    text = path.read_text(encoding="utf-8")
    assert "tasks.py nightly" in text
    assert "reports" in text  # artifacts published for the dashboard


def test_pr_smoke_exists_on_pull_request() -> None:
    path = WORKFLOWS / "pr-smoke.yml"
    assert path.exists(), "PR smoke workflow missing"
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "pull_request" in _triggers(spec)
    text = path.read_text(encoding="utf-8")
    assert "tasks.py test" in text and "tasks.py lint" in text
