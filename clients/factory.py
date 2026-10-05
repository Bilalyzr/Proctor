"""Client factory: settings -> configured model client.

Default is the offline MOCK provider. Real providers are constructed only when
their API key is present (fail-fast via ``Settings.require_api_key``), so a
keyless CI job never reaches a network call.
"""

from __future__ import annotations

from clients.anthropic import AnthropicClient
from clients.base import ModelClient
from clients.gemini import GeminiClient
from clients.mock import MockClient
from clients.openai_adapter import OpenAIClient
from framework.config import Settings


def build_client(settings: Settings) -> ModelClient:
    """Build the provider client named by ``settings.provider``."""
    if settings.provider == "mock":
        return MockClient(
            settings.model_name_for("mock"),
            seed=settings.seed,
        )
    if settings.provider == "gemini":
        return GeminiClient(
            settings.gemini_model,
            api_key=settings.require_api_key("gemini").get_secret_value(),
        )
    if settings.provider == "anthropic":
        return AnthropicClient(
            settings.anthropic_model,
            api_key=settings.require_api_key("anthropic").get_secret_value(),
        )
    if settings.provider == "openai":
        return OpenAIClient(
            settings.openai_model,
            api_key=settings.require_api_key("openai").get_secret_value(),
        )
    msg = f"unknown provider {settings.provider!r}"  # pragma: no cover - Literal guards it
    raise ValueError(msg)
