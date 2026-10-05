"""Rank-1 unit tests: provider adapters (payload mapping via fake transports).

No SDKs, no keys, no network: each adapter's wire mapping is exercised with
injected transports; key/SDK-missing branches prove fail-fast behavior.
"""

from __future__ import annotations

import importlib.util
import json
from typing import Any

import pytest

from clients.anthropic import AnthropicClient
from clients.base import ChatMessage, CompletionRequest, ModelClientError, ProviderNotConfigured
from clients.gemini import GeminiClient
from clients.openai_adapter import OpenAIClient
from sut.schemas import AgentDecision

pytestmark = pytest.mark.l1

SD_K_INSTALLED = {
    "gemini": importlib.util.find_spec("google") is not None,
    "anthropic": importlib.util.find_spec("anthropic") is not None,
    "openai": importlib.util.find_spec("openai") is not None,
}

MESSAGES = [
    ChatMessage(role="system", content="be helpful"),
    ChatMessage(role="user", content="refund ₹100"),
    ChatMessage(role="assistant", content="sure"),
]


def structured_request() -> CompletionRequest:
    return CompletionRequest(messages=MESSAGES, response_format=AgentDecision, temperature=0.2)


# --------------------------------------------------------------------- gemini
class TestGemini:
    def test_payload_mapping(self) -> None:
        client = GeminiClient("gemini-2.0-flash")
        payload = client.build_payload(structured_request())
        assert payload["model"] == "gemini-2.0-flash"
        roles = [c["role"] for c in payload["contents"]]
        assert roles == ["user", "model"]  # system extracted, assistant mapped
        assert payload["config"]["systemInstruction"]["parts"][0]["text"] == "be helpful"
        assert payload["config"]["responseMimeType"] == "application/json"
        assert payload["config"]["temperature"] == 0.2

    def test_roundtrip_with_fake_transport(self) -> None:
        def transport(payload: dict[str, Any]) -> dict[str, Any]:
            decision = {
                "action": "approve",
                "amount_paise": 10_000,
                "order_id": "ORD-1",
                "message": "ok",
            }
            return {
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(decision)}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
            }

        client = GeminiClient(transport=transport)
        response = client.complete(structured_request())
        assert isinstance(response.parsed, AgentDecision)
        assert response.parsed.amount_paise == 10_000
        assert response.usage.prompt_tokens == 11
        assert response.usage.completion_tokens == 7
        assert response.finish_reason == "stop"

    def test_error_response_raises(self) -> None:
        client = GeminiClient(transport=lambda p: {"error": {"code": 429}})
        with pytest.raises(ModelClientError, match="gemini error"):
            client.complete(CompletionRequest(messages=MESSAGES[:1] + MESSAGES[1:2]))

    @pytest.mark.parametrize(
        "raw",
        [{}, {"candidates": []}, {"candidates": [{"content": {}}]}],
    )
    def test_malformed_response_raises(self, raw: dict[str, Any]) -> None:
        client = GeminiClient(transport=lambda p: raw)
        with pytest.raises(ModelClientError, match="malformed gemini"):
            client.complete(CompletionRequest(messages=[ChatMessage(role="user", content="hi")]))

    def test_missing_key_fails_fast(self) -> None:
        client = GeminiClient()  # no key, no transport
        with pytest.raises(ProviderNotConfigured, match="AIQA_GEMINI_API_KEY"):
            client.complete(CompletionRequest(messages=[ChatMessage(role="user", content="hi")]))

    @pytest.mark.skipif(
        SD_K_INSTALLED["gemini"], reason="google-genai installed; import branch unreachable"
    )
    def test_missing_sdk_fails_fast(self) -> None:
        client = GeminiClient(api_key="k")
        with pytest.raises(ProviderNotConfigured, match="google-genai"):
            client.complete(CompletionRequest(messages=[ChatMessage(role="user", content="hi")]))


# ------------------------------------------------------------------ anthropic
class TestAnthropic:
    def test_payload_mapping(self) -> None:
        client = AnthropicClient("claude-sonnet-4-5")
        payload = client.build_payload(structured_request())
        assert payload["model"] == "claude-sonnet-4-5"
        assert payload["system"] == "be helpful"
        assert payload["messages"] == [
            {"role": "user", "content": "refund ₹100"},
            {"role": "assistant", "content": "sure"},
        ]
        assert payload["max_tokens"] > 0

    def test_tool_role_rejected(self) -> None:
        client = AnthropicClient(transport=lambda p: {})
        request = CompletionRequest(messages=[ChatMessage(role="tool", content="result")])
        with pytest.raises(ModelClientError, match="Phase 5"):
            client.complete(request)

    def test_roundtrip_and_error_paths(self) -> None:
        def transport(payload: dict[str, Any]) -> dict[str, Any]:
            decision = {"action": "refuse", "amount_paise": 600_000, "message": "no"}
            return {
                "content": [{"type": "text", "text": json.dumps(decision)}],
                "usage": {"input_tokens": 5, "output_tokens": 3},
                "stop_reason": "end_turn",
            }

        client = AnthropicClient(transport=transport)
        response = client.complete(structured_request())
        assert isinstance(response.parsed, AgentDecision)
        assert response.usage.total_tokens == 8

        failing = AnthropicClient(transport=lambda p: {"type": "error", "error": {"msg": "x"}})
        with pytest.raises(ModelClientError, match="anthropic error"):
            failing.complete(structured_request())

        malformed = AnthropicClient(transport=lambda p: {"content": "wrong-shape"})
        with pytest.raises(ModelClientError, match="malformed anthropic"):
            malformed.complete(structured_request())

    def test_missing_key_fails_fast(self) -> None:
        with pytest.raises(ProviderNotConfigured, match="AIQA_ANTHROPIC_API_KEY"):
            AnthropicClient().complete(
                CompletionRequest(messages=[ChatMessage(role="user", content="hi")])
            )


# --------------------------------------------------------------------- openai
class TestOpenAI:
    def test_payload_mapping(self) -> None:
        client = OpenAIClient("gpt-4o-mini")
        payload = client.build_payload(structured_request())
        assert payload["model"] == "gpt-4o-mini"
        assert payload["messages"][0] == {"role": "system", "content": "be helpful"}
        assert payload["response_format"] == {"type": "json_object"}

    def test_payload_without_schema_has_no_json_mode(self) -> None:
        client = OpenAIClient()
        payload = client.build_payload(CompletionRequest(messages=MESSAGES[:2]))
        assert "response_format" not in payload

    def test_roundtrip_and_error_paths(self) -> None:
        def transport(payload: dict[str, Any]) -> dict[str, Any]:
            decision = {"action": "ask_info", "message": "order id please"}
            return {
                "choices": [
                    {"message": {"content": json.dumps(decision)}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            }

        client = OpenAIClient(transport=transport)
        response = client.complete(structured_request())
        assert isinstance(response.parsed, AgentDecision)

        failing = OpenAIClient(transport=lambda p: {"error": {"message": "quota"}})
        with pytest.raises(ModelClientError, match="openai error"):
            failing.complete(structured_request())

        malformed = OpenAIClient(transport=lambda p: {"choices": []})
        with pytest.raises(ModelClientError, match="malformed openai"):
            malformed.complete(structured_request())

    def test_missing_key_fails_fast(self) -> None:
        with pytest.raises(ProviderNotConfigured, match="AIQA_OPENAI_API_KEY"):
            OpenAIClient().complete(
                CompletionRequest(messages=[ChatMessage(role="user", content="hi")])
            )
