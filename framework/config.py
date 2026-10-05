"""Framework configuration.

All settings come from environment variables (optionally a local ``.env`` file)
via pydantic-settings. Secrets are never hard-coded; real providers are enabled
only by the presence of their API key (Rule 4 / SEC-2 posture).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised when the requested configuration cannot be used safely."""


class Settings(BaseSettings):
    """Versioned generation + harness parameters (EVL-2)."""

    model_config = SettingsConfigDict(
        env_prefix="AIQA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # provider selection
    provider: Literal["mock", "gemini", "anthropic", "openai"] = "mock"
    tier: Literal["critical", "high", "standard"] = "critical"

    # model names per provider
    gemini_model: str = "gemini-2.0-flash"
    anthropic_model: str = "claude-sonnet-4-5"
    openai_model: str = "gpt-4o-mini"

    # generation parameters (EVL-2: explicit and recorded into every run log)
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 1024
    seed: int = 42
    repeat_runs: int = 5

    # input sanitization (EVL-2)
    sanitize_max_chars: int = 8000
    sanitize_strip_markup: bool = True

    # harness
    log_dir: Path = Path("reports")
    thresholds_dir: Path = Path("thresholds")

    # secrets - optional, env-only, never logged (SecretStr)
    gemini_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def _check_ranges(self) -> Settings:
        if not 0.0 <= self.temperature <= 2.0:
            msg = f"temperature must be in [0, 2], got {self.temperature}"
            raise ValueError(msg)
        if not 0.0 <= self.top_p <= 1.0:
            msg = f"top_p must be in [0, 1], got {self.top_p}"
            raise ValueError(msg)
        if self.max_tokens < 1:
            msg = f"max_tokens must be >= 1, got {self.max_tokens}"
            raise ValueError(msg)
        if self.repeat_runs < 1:
            msg = f"repeat_runs must be >= 1, got {self.repeat_runs}"
            raise ValueError(msg)
        if self.sanitize_max_chars < 1:
            msg = f"sanitize_max_chars must be >= 1, got {self.sanitize_max_chars}"
            raise ValueError(msg)
        return self

    def model_name_for(self, provider: str) -> str:
        """Return the configured model name for a provider."""
        names: dict[str, str] = {
            "mock": "mock-refund-assistant-v1",
            "gemini": self.gemini_model,
            "anthropic": self.anthropic_model,
            "openai": self.openai_model,
        }
        try:
            return names[provider]
        except KeyError as exc:
            msg = f"unknown provider {provider!r}"
            raise ConfigurationError(msg) from exc

    def require_api_key(self, provider: str) -> SecretStr:
        """Return the API key for a real provider or raise ConfigurationError.

        The MOCK provider never calls this; real adapters call it in their
        constructor so a keyless CI job fails fast with a clear message instead
        of attempting a network call.
        """
        keys: dict[str, SecretStr | None] = {
            "gemini": self.gemini_api_key,
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }
        try:
            key = keys[provider]
        except KeyError as exc:
            msg = f"unknown provider {provider!r}"
            raise ConfigurationError(msg) from exc
        if key is None or not key.get_secret_value().strip():
            msg = (
                f"provider {provider!r} requires an API key; set "
                f"AIQA_{provider.upper()}_API_KEY or use AIQA_PROVIDER=mock"
            )
            raise ConfigurationError(msg)
        return key

    def generation_params(self) -> dict[str, object]:
        """Snapshot of generation parameters recorded with every run (AST-1/EVL-2)."""
        return {
            "provider": self.provider,
            "model": self.model_name_for(self.provider),
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "seed": self.seed,
            "repeat_runs": self.repeat_runs,
            "sanitize_max_chars": self.sanitize_max_chars,
            "sanitize_strip_markup": self.sanitize_strip_markup,
            "tier": self.tier,
        }
