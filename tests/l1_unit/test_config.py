"""Rank-1 unit tests: configuration (EVL-2 - explicit, versioned parameters)."""

from __future__ import annotations

import pytest

from framework.config import ConfigurationError, Settings

pytestmark = pytest.mark.l1


def test_defaults_are_offline_safe() -> None:
    s = Settings(_env_file=None)
    assert s.provider == "mock"
    assert s.tier == "critical"
    assert s.temperature == 0.0
    assert s.repeat_runs == 5
    assert s.seed == 42
    assert s.gemini_api_key is None
    assert s.anthropic_api_key is None
    assert s.openai_api_key is None


def test_env_overrides_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIQA_PROVIDER", "gemini")
    monkeypatch.setenv("AIQA_TEMPERATURE", "0.7")
    monkeypatch.setenv("AIQA_REPEAT_RUNS", "30")
    monkeypatch.setenv("AIQA_SANITIZE_MAX_CHARS", "100")
    s = Settings(_env_file=None)
    assert s.provider == "gemini"
    assert s.temperature == 0.7
    assert s.repeat_runs == 30
    assert s.sanitize_max_chars == 100


def test_secrets_never_serialize_as_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIQA_GEMINI_API_KEY", "super-secret")
    s = Settings(_env_file=None)
    dumped = repr(s.model_dump())
    assert "super-secret" not in dumped


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("AIQA_TEMPERATURE", "-0.1"),
        ("AIQA_TEMPERATURE", "2.5"),
        ("AIQA_TOP_P", "1.5"),
        ("AIQA_MAX_TOKENS", "0"),
        ("AIQA_REPEAT_RUNS", "0"),
        ("AIQA_SANITIZE_MAX_CHARS", "0"),
        ("AIQA_PROVIDER", "bedrock"),  # not a supported provider
    ],
)
def test_invalid_values_rejected(monkeypatch: pytest.MonkeyPatch, field: str, value: str) -> None:
    monkeypatch.setenv(field, value)
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_model_name_for_each_provider() -> None:
    s = Settings(_env_file=None)
    assert s.model_name_for("mock").startswith("mock-")
    assert s.model_name_for("gemini").startswith("gemini-")
    assert s.model_name_for("anthropic").startswith("claude-")
    assert s.model_name_for("openai").startswith("gpt-")
    with pytest.raises(ConfigurationError):
        s.model_name_for("unknown")


def test_require_api_key_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None)
    with pytest.raises(ConfigurationError, match="AIQA_GEMINI_API_KEY"):
        s.require_api_key("gemini")
    with pytest.raises(ConfigurationError):
        s.require_api_key("unknown")
    monkeypatch.setenv("AIQA_GEMINI_API_KEY", "k-123")
    s2 = Settings(_env_file=None)
    assert s2.require_api_key("gemini").get_secret_value() == "k-123"
    # blank keys count as missing
    monkeypatch.setenv("AIQA_ANTHROPIC_API_KEY", "   ")
    s3 = Settings(_env_file=None)
    with pytest.raises(ConfigurationError):
        s3.require_api_key("anthropic")


def test_generation_params_snapshot_is_complete() -> None:
    """EVL-2/AST-1: every generation parameter appears in the run snapshot."""
    s = Settings(_env_file=None)
    snap = s.generation_params()
    for key in (
        "provider",
        "model",
        "temperature",
        "top_p",
        "max_tokens",
        "seed",
        "repeat_runs",
        "sanitize_max_chars",
        "sanitize_strip_markup",
        "tier",
    ):
        assert key in snap
    # secrets must never appear in the parameter snapshot
    assert not any("key" in k.lower() for k in snap)
