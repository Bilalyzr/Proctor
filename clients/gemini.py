"""Gemini adapter (google-genai SDK, lazy import).

The wire mapping is pure and unit-tested with injected fake transports; the
real network path activates only when the SDK is installed and an API key was
provided by the factory. Structured output uses responseMimeType application/json
plus schema validation on the way back.
"""

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


class GeminiClient(BaseClient):
    provider = "gemini"
    default_model = "gemini-2.0-flash"

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
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]
        config: dict[str, Any] = {
            "temperature": resolved["temperature"],
            "topP": resolved["top_p"],
            "maxOutputTokens": resolved["max_tokens"],
        }
        if system_parts:
            config["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if request.response_format is not None:
            config["responseMimeType"] = "application/json"
        return {"model": resolved["model"], "contents": contents, "config": config}

    def parse_response(self, raw: dict[str, Any], request: CompletionRequest) -> CompletionResponse:
        if "error" in raw:
            msg = f"gemini error: {raw['error']}"
            raise ModelClientError(msg)
        try:
            candidate = raw["candidates"][0]
            text = "".join(part["text"] for part in candidate["content"]["parts"] if "text" in part)
            usage_meta = raw.get("usageMetadata", {})
            usage = TokenUsage(
                prompt_tokens=int(usage_meta.get("promptTokenCount", 0)),
                completion_tokens=int(usage_meta.get("candidatesTokenCount", 0)),
            )
            finish = str(candidate.get("finishReason", "stop")).lower()
        except (KeyError, IndexError, TypeError) as exc:
            msg = f"malformed gemini response: {raw!r:.200}"
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
            msg = "gemini selected but no API key; set AIQA_GEMINI_API_KEY or use mock"
            raise ProviderNotConfigured(msg)
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as exc:
            msg = "google-genai not installed; pip install 'proctor[gemini]'"
            raise ProviderNotConfigured(msg) from exc
        client = genai.Client(api_key=self._api_key)  # pragma: no cover
        response = client.models.generate_content(  # pragma: no cover
            model=payload["model"],
            contents=payload["contents"],
            config=payload["config"],
        )
        return response.model_dump()  # pragma: no cover
