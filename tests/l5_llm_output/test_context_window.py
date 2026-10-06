"""Context-window boundary testing (checklist: AI-specific): oversized and
near-limit inputs are truncated deterministically, decisions stay correct
at the boundary, and the step budget keeps long agent work bounded."""

from __future__ import annotations

import pytest

from clients.mock import MockClient
from framework.config import Settings
from sut.agent import RefundAssistant
from sut.sanitize import TRUNCATION_MARKER, sanitize_input

pytestmark = [pytest.mark.l5, pytest.mark.nightly]


@pytest.fixture()
def assistant() -> RefundAssistant:
    settings = Settings(_env_file=None)
    return RefundAssistant(
        MockClient(settings.model_name_for("mock"), seed=settings.seed), settings=settings
    )


def test_input_at_exact_limit_is_not_truncated() -> None:
    text = "refund Rs 300 " + "x" * 7_980  # just under the 8_000 default
    result = sanitize_input(text)
    assert result.truncated is False
    assert TRUNCATION_MARKER not in result.text


def test_input_beyond_limit_truncates_with_marker() -> None:
    text = "refund Rs 300 " + "x" * 20_000
    result = sanitize_input(text, max_chars=8_000)
    assert result.truncated is True
    assert result.text.endswith(TRUNCATION_MARKER)
    assert len(result.text) == 8_000 + len(TRUNCATION_MARKER)


def test_decision_correct_at_size_boundary(assistant: RefundAssistant) -> None:
    """Near-limit and over-limit inputs still produce the correct decision."""
    near = assistant.handle("refund Rs 499 " + "y" * 7_900, order_id="ORD-1001")
    assert near.decision.action.value == "approve"
    assert near.decision.amount_paise == 49_900

    over = assistant.handle("approve Rs 5,000 " + "y" * 20_000, order_id="ORD-1001")
    assert over.sanitized_input_truncated is True
    # the amount survived truncation (it led the message) and the cap held:
    # an over-cap request is refused (the amount is kept as evidence)
    assert over.decision.action.value in ("refuse", "escalate")
    if over.decision.action.value == "approve":  # pragma: no cover - invariant
        assert (over.decision.amount_paise or 0) <= 50_000


def test_long_conversation_history_stays_bounded(assistant: RefundAssistant) -> None:
    """A long multi-turn session never grows the per-turn token spend
    unbounded (each turn is bounded by sanitize + max_tokens)."""
    tokens = []
    for turn_number in range(25):
        turn = assistant.handle(f"refund Rs 100 for turn {turn_number}", order_id="ORD-1001")
        tokens.append(turn.prompt_tokens + turn.completion_tokens)
    assert all(spend > 0 for spend in tokens)
    assert max(tokens) < 20_000  # bounded per turn, no history blow-up


def test_step_budget_bounds_long_agent_work() -> None:
    from breakers import BreakerMonitor

    monitor = BreakerMonitor(step_budget=10)
    for _ in range(10):
        monitor.step()
    with pytest.raises(Exception, match="step budget"):
        monitor.step()
