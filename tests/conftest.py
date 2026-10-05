"""Shared fixtures for the whole test tree.

Settings fixtures always pass ``_env_file=None`` so a developer's local .env
never leaks into test expectations; env vars still apply (monkeypatch them).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import settings as hypothesis_settings

# Windows CI: wall-clock deadlines flake; keep property tests fast but solid.
hypothesis_settings.register_profile("aiqa", deadline=None, max_examples=50)
hypothesis_settings.load_profile("aiqa")

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def settings() -> object:
    from framework.config import Settings

    return Settings(_env_file=None)


@pytest.fixture()
def mock_client(settings: object) -> object:
    from clients.mock import MockClient

    return MockClient(settings.model_name_for("mock"), seed=settings.seed)  # type: ignore[attr-defined]


@pytest.fixture()
def run_logger(tmp_path: Path):
    from framework.runlog import RunLogger

    logger = RunLogger(log_dir=tmp_path / "reports", suite="unit-tests")
    logger.open()
    yield logger
    logger.close()
