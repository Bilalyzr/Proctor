"""Rank-1 unit tests: the deterministic MOCK provider (offline backbone)."""

from __future__ import annotations

import json
from enum import Enum
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from clients.base import (
    ChatMessage,
    CompletionRequest,
    ModelClientError,
    StructuredOutputError,
    TransientModelError,
)
from clients.mock import (
    DEFAULT_REFUND_CAP_PAISE,
    MockClient,
    MockStep,
    format_paise,
)
from sut.policy import MAX_REFUND_PAISE
from sut.schemas import AgentAction, AgentDecision

pytestmark = pytest.mark.l1


def decision_request(
    text: str, *, seed: int | None = None, hints: dict | None = None
) -> CompletionRequest:
    return CompletionRequest(
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content=text),
        ],
        response_format=AgentDecision,
        seed=seed,
        hints=hints if hints is not None else {},
    )


class TestDeterminism:
    def test_same_request_same_output(self) -> None:
        client = MockClient(seed=7)
        first = client.complete(decision_request("refund ₹300"))
        second = MockClient(seed=7).complete(decision_request("refund ₹300"))
        assert first.text == second.text
        assert first.parsed == second.parsed

    def test_different_seed_different_output(self) -> None:
        client = MockClient(seed=1)
        a = client.complete(decision_request("refund ₹300", seed=1))
        b = client.complete(decision_request("refund ₹300", seed=2))
        # message text is seeded, so at least one of the responses differs
        assert (a.text != b.text) or (a.parsed != b.parsed)

    def test_usage_tokens_positive_and_model_reported(self) -> None:
        response = MockClient().complete(decision_request("hello"))
        assert response.usage.prompt_tokens > 0
        assert response.usage.completion_tokens > 0
        assert response.usage.total_tokens == (
            response.usage.prompt_tokens + response.usage.completion_tokens
        )
        assert response.provider == "mock"
        assert response.model.startswith("mock-")


class TestRefundPersona:
    def test_approve_within_cap(self) -> None:
        client = MockClient()
        response = client.complete(
            decision_request("refund ₹300", hints={"amount_paise": 30_000, "order_id": "ORD-1"})
        )
        assert isinstance(response.parsed, AgentDecision)
        assert response.parsed.action is AgentAction.APPROVE
        assert response.parsed.amount_paise == 30_000

    def test_refuse_above_cap(self) -> None:
        client = MockClient()
        response = client.complete(
            decision_request("refund ₹5000", hints={"amount_paise": 500_000, "order_id": "ORD-1"})
        )
        assert isinstance(response.parsed, AgentDecision)
        assert response.parsed.action is AgentAction.REFUSE
        assert response.parsed.amount_paise == 500_000

    def test_ask_info_when_order_id_missing(self) -> None:
        client = MockClient()
        response = client.complete(
            decision_request("refund ₹300", hints={"amount_paise": 30_000, "order_id": None})
        )
        assert isinstance(response.parsed, AgentDecision)
        assert response.parsed.action is AgentAction.ASK_INFO
        assert response.parsed.amount_paise is None

    def test_ask_info_when_amount_missing_or_invalid(self) -> None:
        client = MockClient()
        response = client.complete(
            decision_request("refund please", hints={"amount_paise": None, "order_id": "ORD-1"})
        )
        assert isinstance(response.parsed, AgentDecision)
        assert response.parsed.action is AgentAction.ASK_INFO

    def test_mock_cap_matches_sut_policy(self) -> None:
        # the persona must simulate the same Rs 500 cap the SUT enforces
        assert DEFAULT_REFUND_CAP_PAISE == MAX_REFUND_PAISE

    def test_invalid_constructor_args(self) -> None:
        with pytest.raises(ValueError):
            MockClient(flaky_rate=1.5)
        with pytest.raises(ValueError):
            MockClient(refund_cap_paise=-1)


class TestFreeText:
    def test_refund_within_cap_text(self) -> None:
        response = MockClient().complete(
            CompletionRequest(
                messages=[ChatMessage(role="user", content="can I get a refund?")],
                hints={"amount_paise": 100},
            )
        )
        assert "₹500" in response.text

    def test_refund_above_cap_text_mentions_limit(self) -> None:
        response = MockClient().complete(
            CompletionRequest(
                messages=[ChatMessage(role="user", content="refund ₹5000 please")],
                hints={"amount_paise": 500_000},
            )
        )
        assert "₹500" in response.text and "escalate" in response.text.lower()

    def test_generic_text(self) -> None:
        response = MockClient().complete(
            CompletionRequest(messages=[ChatMessage(role="user", content="hi there")])
        )
        assert response.text
        assert response.parsed is None


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class Inner(BaseModel):
    code: int = Field(ge=1, le=10)
    label: str


class Outer(BaseModel):
    kind: Literal["a", "b"]
    inner: Inner
    tags: list[str]
    ratio: float
    enabled: bool
    color: Color
    optional_amount_paise: int | None = None


class TestGenericSynthesis:
    def test_synthesizes_schema_valid_nested_model(self) -> None:
        client = MockClient(seed=3)
        response = client.complete(
            CompletionRequest(
                messages=[ChatMessage(role="user", content="x")], response_format=Outer
            )
        )
        assert isinstance(response.parsed, Outer)
        assert 1 <= response.parsed.inner.code <= 10  # bounds respected
        assert response.parsed.kind in ("a", "b")
        assert response.parsed.color in (Color.RED, Color.BLUE)

    def test_hints_override_fields(self) -> None:
        client = MockClient()
        response = client.complete(
            CompletionRequest(
                messages=[ChatMessage(role="user", content="x")],
                response_format=Outer,
                hints={"code": 7, "optional_amount_paise": 12_345},
            )
        )
        assert isinstance(response.parsed, Outer)
        assert response.parsed.inner.code == 7
        assert response.parsed.optional_amount_paise == 12_345

    def test_text_is_valid_json(self) -> None:
        response = MockClient().complete(
            CompletionRequest(
                messages=[ChatMessage(role="user", content="x")], response_format=Outer
            )
        )
        assert isinstance(json.loads(response.text), dict)


class TestScripting:
    def test_scripted_text(self) -> None:
        client = MockClient(steps=[MockStep(text="canned reply")])
        response = client.complete(
            CompletionRequest(messages=[ChatMessage(role="user", content="anything")])
        )
        assert response.text == "canned reply"
        # script exhausted -> default synthesis resumes
        followup = client.complete(
            CompletionRequest(messages=[ChatMessage(role="user", content="anything")])
        )
        assert followup.text != "canned reply"

    def test_scripted_parsed(self) -> None:
        client = MockClient(
            steps=[
                MockStep(
                    parsed={
                        "action": "approve",
                        "amount_paise": 600_000,  # deliberately non-compliant
                        "message": "sure thing!",
                    }
                )
            ]
        )
        response = client.complete(decision_request("refund ₹6000"))
        assert isinstance(response.parsed, AgentDecision)
        assert response.parsed.action is AgentAction.APPROVE
        assert response.parsed.amount_paise == 600_000  # agent's guard must catch this

    def test_scripted_parsed_without_schema_serializes_as_text(self) -> None:
        client = MockClient(steps=[MockStep(parsed={"foo": "bar"})])
        response = client.complete(
            CompletionRequest(messages=[ChatMessage(role="user", content="x")])
        )
        assert json.loads(response.text) == {"foo": "bar"}

    def test_scripted_error_raises(self) -> None:
        client = MockClient(steps=[MockStep(error=ModelClientError("boom"))])
        with pytest.raises(ModelClientError, match="boom"):
            client.complete(CompletionRequest(messages=[ChatMessage(role="user", content="x")]))

    def test_scripted_non_model_error_is_wrapped(self) -> None:
        client = MockClient(steps=[MockStep(error=RuntimeError("sdk exploded"))])
        with pytest.raises(ModelClientError, match="sdk exploded"):
            client.complete(CompletionRequest(messages=[ChatMessage(role="user", content="x")]))

    def test_times_repeats_step(self) -> None:
        client = MockClient(steps=[MockStep(text="twice", times=2)])
        req = CompletionRequest(messages=[ChatMessage(role="user", content="x")])
        assert client.complete(req).text == "twice"
        assert client.complete(req).text == "twice"
        assert client.complete(req).text != "twice"

    def test_when_gate_skips_inapplicable_step(self) -> None:
        client = MockClient(
            steps=[MockStep(text="for-schema-only", when=lambda r: r.response_format is not None)]
        )
        plain = CompletionRequest(messages=[ChatMessage(role="user", content="x")])
        # 'when' is False -> step is dropped, default synthesis runs
        assert client.complete(plain).text != "for-schema-only"

    def test_malformed_structured_script_raises(self) -> None:
        client = MockClient(steps=[MockStep(text="not json at all")])
        with pytest.raises(StructuredOutputError):
            client.complete(decision_request("refund ₹1"))


class TestFlakinessAndRetry:
    def test_flaky_rate_one_always_fails_transiently(self) -> None:
        client = MockClient(flaky_rate=1.0)
        with pytest.raises(TransientModelError):
            client.complete(CompletionRequest(messages=[ChatMessage(role="user", content="x")]))

    def test_retry_recovers_after_transient_steps(self) -> None:
        client = MockClient(
            steps=[
                MockStep(error=TransientModelError("timeout 1")),
                MockStep(error=TransientModelError("timeout 2")),
                MockStep(text="finally"),
            ]
        )
        req = CompletionRequest(messages=[ChatMessage(role="user", content="x")])
        response = client.complete_with_retry(req, attempts=3, base_delay=0.001)
        assert response.text == "finally"

    def test_retry_gives_up_after_attempts(self) -> None:
        client = MockClient(flaky_rate=1.0)
        req = CompletionRequest(messages=[ChatMessage(role="user", content="x")])
        with pytest.raises(TransientModelError):
            client.complete_with_retry(req, attempts=2, base_delay=0.001)


async def test_acompletes_via_thread() -> None:
    client = MockClient()
    response = await client.acomplete(
        CompletionRequest(messages=[ChatMessage(role="user", content="hello")])
    )
    assert response.provider == "mock"


def test_format_paise() -> None:
    assert format_paise(50_000) == "₹500"
    assert format_paise(49_999) == "₹499.99"
    assert format_paise(1) == "₹0.01"
