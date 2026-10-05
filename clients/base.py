"""Core types for the provider-agnostic model client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class ModelClientError(Exception):
    """Base class for model-client failures."""


class TransientModelError(ModelClientError):
    """A retryable failure (timeout, 5xx, rate limit)."""


class StructuredOutputError(ModelClientError):
    """The model returned output that does not validate against the schema."""


class ProviderNotConfigured(ModelClientError):
    """A real provider was selected without its SDK or API key."""


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One conversation turn."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass(slots=True)
class TokenUsage:
    """Token accounting (MCP-2 groundwork: tracked per request and per tool)."""

    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(slots=True)
class CompletionRequest:
    """One completion call.

    Field-level overrides win over client defaults; ``response_format`` requests
    structured output validated against a Pydantic model (EVL-2); ``hints``
    carry deterministic cues for the MOCK provider (extracted amounts, order
    IDs) so offline runs produce coherent, schema-valid responses.
    """

    messages: list[ChatMessage]
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    response_format: type[BaseModel] | None = None
    hints: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CompletionResponse:
    """Normalized completion result across providers."""

    text: str
    usage: TokenUsage
    provider: str
    model: str
    finish_reason: str = "stop"
    parsed: BaseModel | None = None


@runtime_checkable
class ModelClient(Protocol):
    """The single method every provider adapter implements."""

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...


class BaseClient:
    """Shared plumbing: parameter resolution, async wrapper, retries.

    Subclasses set ``provider``/``default_model`` and implement ``complete``.
    """

    provider: str = "base"
    default_model: str = "unknown"

    def __init__(
        self,
        model: str | None = None,
        *,
        temperature: float = 0.0,
        top_p: float = 1.0,
        max_tokens: int = 1024,
        seed: int = 42,
    ) -> None:
        self.model = model or self.default_model
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.seed = seed

    @property
    def provider_model(self) -> str:
        return self.model

    def _resolved(self, request: CompletionRequest) -> dict[str, Any]:
        """Request-level overrides applied over client defaults."""
        return {
            "model": request.model or self.model,
            "temperature": self.temperature if request.temperature is None else request.temperature,
            "top_p": self.top_p if request.top_p is None else request.top_p,
            "max_tokens": self.max_tokens if request.max_tokens is None else request.max_tokens,
            "seed": self.seed if request.seed is None else request.seed,
        }

    def complete(self, request: CompletionRequest) -> CompletionResponse:  # pragma: no cover
        raise NotImplementedError

    async def acomplete(self, request: CompletionRequest) -> CompletionResponse:
        """Async facade over the sync call for the sharded runner (Phase 4)."""
        return await asyncio.to_thread(self.complete, request)

    def complete_with_retry(
        self,
        request: CompletionRequest,
        *,
        attempts: int = 3,
        base_delay: float = 0.05,
        retry_on: tuple[type[BaseException], ...] = (TransientModelError,),
    ) -> CompletionResponse:
        """Retry transient failures with exponential backoff (tenacity)."""
        from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

        retryer = Retrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=base_delay),
            retry=retry_if_exception_type(retry_on),
            reraise=True,
        )
        return retryer(self.complete, request)
