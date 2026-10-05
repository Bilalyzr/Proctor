"""Rank-1 unit tests: client factory (offline default, fail-fast real providers)."""

from __future__ import annotations

import pytest

from clients.anthropic import AnthropicClient
from clients.base import ModelClient
from clients.factory import build_client
from clients.gemini import GeminiClient
from clients.mock import MockClient as RealMockClient
from clients.openai_adapter import OpenAIClient
from framework.config import ConfigurationError, Settings

pytestmark = pytest.mark.l1


def test_default_is_offline_mock() -> None:
    client = build_client(Settings(_env_file=None))
    assert isinstance(client, RealMockClient)
    assert isinstance(client, ModelClient)  # protocol-conformant


@pytest.mark.parametrize("provider", ["gemini", "anthropic", "openai"])
def test_real_provider_without_key_raises(provider: str) -> None:
    with pytest.raises(ConfigurationError):
        build_client(Settings(_env_file=None, provider=provider))  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("provider", "expected_cls", "env_key", "model_env"),
    [
        ("gemini", GeminiClient, "AIQA_GEMINI_API_KEY", "AIQA_GEMINI_MODEL"),
        ("anthropic", AnthropicClient, "AIQA_ANTHROPIC_API_KEY", "AIQA_ANTHROPIC_MODEL"),
        ("openai", OpenAIClient, "AIQA_OPENAI_API_KEY", "AIQA_OPENAI_MODEL"),
    ],
)
def test_real_provider_with_key_builds(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    expected_cls: type,
    env_key: str,
    model_env: str,
) -> None:
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setenv(model_env, "custom-model-x")
    client = build_client(Settings(_env_file=None, provider=provider))  # type: ignore[call-arg]
    assert isinstance(client, expected_cls)
    assert client.provider_model == "custom-model-x"
