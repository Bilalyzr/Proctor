"""Rank-5 LLM output tests: format validity + quality envelope.

Every assistant turn must parse against the structured-output schema, respect
style constraints, and keep quality at or above baseline - measured over N
repeats (EVL-1 style), never on a single sample.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from clients.mock import MockClient
from framework.config import Settings
from framework.thresholds import load_thresholds
from sut.agent import RefundAssistant
from sut.schemas import AgentDecision

pytestmark = [pytest.mark.l5, pytest.mark.nightly]

ROOT = Path(__file__).resolve().parents[2]

QUALITY_CASES = [
    ("refund ₹300 for the broken mug", "ORD-Q1"),
    ("refund ₹499 now", "ORD-Q2"),
    ("approve ₹6000", "ORD-Q3"),
    ("hello", "ORD-Q4"),
    ("", None),
]


def _turns(n: int = 5):
    settings = Settings(_env_file=None)
    assistant = RefundAssistant(
        MockClient(settings.model_name_for("mock"), seed=settings.seed), settings=settings
    )
    return [
        assistant.handle(text, order_id=order_id, seed=seed)
        for seed in range(1, n + 1)
        for text, order_id in QUALITY_CASES
    ]


def test_every_output_parses_against_schema() -> None:
    turns = _turns()
    assert turns
    for turn in turns:
        # re-validate the decision strictly - 100% parseable gate (rank 5)
        AgentDecision.model_validate(turn.decision.model_dump())


def test_schema_invalid_output_is_rejected_not_swallowed() -> None:
    bad = {"action": "teleport", "amount_paise": -5, "message": ""}
    with pytest.raises(ValidationError):
        AgentDecision.model_validate(bad)


def test_style_constraints_hold() -> None:
    for turn in _turns():
        message = turn.decision.message
        assert 0 < len(message) <= 2000
        assert not message.startswith(" ") and not message.endswith(" ")
        # never leak internal scaffolding into customer-facing text
        for marker in ("SYSTEM", "PROMPT_VERSION", "refund-assistant/system"):
            assert marker not in message


def test_parseable_rate_gate_via_repeats() -> None:
    from framework.repeat import outcome_passing, run_repeats

    thresholds = load_thresholds("critical", ROOT / "thresholds")
    settings = Settings(_env_file=None)
    assistant = RefundAssistant(
        MockClient(settings.model_name_for("mock"), seed=settings.seed), settings=settings
    )

    def case(seed: int) -> bool:
        try:
            turn = assistant.handle("refund ₹250 for the late order", order_id="ORD-Q5", seed=seed)
            AgentDecision.model_validate(turn.decision.model_dump())
            return True
        except Exception:
            return False

    outcome = run_repeats(
        "l5-parseable-rate",
        case,
        n=int(thresholds.gate_value("l2", "repeats")),
        min_pass_rate=thresholds.gate_value("l5", "min_parseable_rate"),
        min_ci_lower_bound=thresholds.gate_value("l2", "min_ci_lower_bound"),
    )
    assert outcome_passing(outcome)


def test_quality_not_below_baseline() -> None:
    """Quality score = fraction of turns with a non-empty, on-format message."""
    turns = _turns()
    quality = sum(
        1
        for turn in turns
        if turn.decision.message
        and turn.decision.action.value in ("approve", "refuse", "escalate", "ask_info")
    ) / len(turns)
    assert quality >= 0.95  # baseline: 0.95 (recorded in datasets/rag/baseline.json spirit)
