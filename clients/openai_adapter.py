"""OpenAI adapter (openai SDK, lazy import, injectable transport)."""

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


class OpenAIClient(BaseClient):
    provider = "openai"
    default_model = "gpt-4o-mini"

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
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("system", "user", "assistant")
        ]
        payload: dict[str, Any] = {
            "model": resolved["model"],
            "messages": messages,
            "temperature": resolved["temperature"],
            "top_p": resolved["top_p"],
            "max_tokens": resolved["max_tokens"],
        }
        if request.response_format is not None:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def parse_response(self, raw: dict[str, Any], request: CompletionRequest) -> CompletionResponse:
        if raw.get("error"):
            msg = f"openai error: {raw['error']}"
            raise ModelClientError(msg)
        try:
            text = raw["choices"][0]["message"]["content"] or ""
            usage_raw = raw.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
                completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            )
            finish = str(raw["choices"][0].get("finish_reason", "stop"))
        except (KeyError, IndexError, TypeError) as exc:
            msg = f"malformed openai response: {raw!r:.200}"
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
            msg = "openai selected but no API key; set AIQA_OPENAI_API_KEY"
            raise ProviderNotConfigured(msg)
        try:
            import openai as openai_sdk  # type: ignore[import-not-found]
        except ImportError as exc:
            msg = "openai not installed; pip install 'ai-qa-framework[openai]'"
            raise ProviderNotConfigured(msg) from exc
        client = openai_sdk.OpenAI(api_key=self._api_key)  # pragma: no cover
        response = client.chat.completions.create(**payload)  # pragma: no cover
        return response.model_dump()  # pragma: no cover
