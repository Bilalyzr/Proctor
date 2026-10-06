"""Anthropic adapter (anthropic SDK, lazy import, injectable transport)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from clients._structured import parse_structured
from clients.base import (
    BaseClient,
    CompletionRequest,
    CompletionResponse,
    ModelClientError,
    ProviderNotConfigured,
    TokenUsage,
)

Transport = Callable[[dict[str, Any]], dict[str, Any]]


class AnthropicClient(BaseClient):
    provider = "anthropic"
    default_model = "claude-sonnet-4-5"

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(model)
        self._api_key = api_key
        self._transport = transport

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload = self.build_payload(request)
        raw = self._call(payload)
        return self.parse_response(raw, request)

    # ------------------------------------------------------------ wire map
    def build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        resolved = self._resolved(request)
        system_parts = [m.content for m in request.messages if m.role == "system"]
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]
        for message in request.messages:
            if m_role_unsupported(message.role):
                msg = "tool messages are not supported by this adapter until Phase 5"
                raise ModelClientError(msg)
        payload: dict[str, Any] = {
            "model": resolved["model"],
            "messages": messages,
            "max_tokens": resolved["max_tokens"],
            "temperature": resolved["temperature"],
            "top_p": resolved["top_p"],
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        return payload

    def parse_response(self, raw: dict[str, Any], request: CompletionRequest) -> CompletionResponse:
        if raw.get("type") == "error":
            msg = f"anthropic error: {raw.get('error')}"
            raise ModelClientError(msg)
        try:
            content = raw["content"]
            if not isinstance(content, list):
                msg = f"malformed anthropic response: {raw!r:.200}"
                raise ModelClientError(msg)
            text = "".join(block["text"] for block in content if block.get("type") == "text")
            usage_raw = raw.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=int(usage_raw.get("input_tokens", 0)),
                completion_tokens=int(usage_raw.get("output_tokens", 0)),
            )
            finish = str(raw.get("stop_reason", "end_turn"))
        except (KeyError, TypeError) as exc:
            msg = f"malformed anthropic response: {raw!r:.200}"
            raise ModelClientError(msg) from exc
        parsed: BaseModel | None = None
        if request.response_format is not None:
            parsed = parse_structured(text, request.response_format)
        return CompletionResponse(
            text=text,
            usage=usage,
            provider=self.provider,
            model=self.provider_model,
            finish_reason=finish,
            parsed=parsed,
        )

    # ------------------------------------------------------------ real path
    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._transport is not None:
            return self._transport(payload)
        if not self._api_key:
            msg = "anthropic selected but no API key; set AIQA_ANTHROPIC_API_KEY"
            raise ProviderNotConfigured(msg)
        try:
            import anthropic as anthropic_sdk  # type: ignore[import-not-found]
        except ImportError as exc:
            msg = "anthropic not installed; pip install 'proctor[anthropic]'"
            raise ProviderNotConfigured(msg) from exc
        client = anthropic_sdk.Anthropic(api_key=self._api_key)  # pragma: no cover
        response = client.messages.create(**payload)  # pragma: no cover
        return response.model_dump()  # pragma: no cover


def m_role_unsupported(role: str) -> bool:
    return role not in ("system", "user", "assistant")
