"""Rank-1 unit tests: the Rs 500 refund cap policy engine (blueprint Section 1).

This is the canonical money-safety invariant - negative, zero, non-numeric and
boundary amounts, plus Hypothesis properties that hold for *any* input.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sut.policy import (
    MAX_REFUND_PAISE,
    AmountParsingError,
    NegativeAmountError,
    enforce_policy,
    evaluate_refund,
    is_within_cap,
    parse_amount,
)
from sut.schemas import AgentAction, AgentDecision

pytestmark = pytest.mark.l1


@pytest.mark.parametrize(
    ("text", "expected_paise"),
    [
        ("refund ₹500", 50_000),
        ("refund Rs 500", 50_000),
        ("refund rs.499.99", 49_999),
        ("INR 499 please", 49_900),
        ("I want 250 back", 25_000),
        ("₹1,200.50", 120_050),
        ("₹1,20,000", 12_000_000),  # Indian grouping
        ("₹120,000", 12_000_000),  # western grouping
        ("refund ₹250 on 2024-01-15", 25_000),  # currency-marked wins over date
        ("₹0.01", 1),
    ],
)
def test_parse_amount_variants(text: str, expected_paise: int) -> None:
    assert parse_amount(text) == expected_paise


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no numbers here",
        "₹",
        "refund my money please",
    ],
)
def test_parse_amount_rejects_garbage(text: str) -> None:
    with pytest.raises(AmountParsingError):
        parse_amount(text)


@pytest.mark.parametrize(
    "text",
    [
        "refund ₹-500",  # minus after the currency marker
        "₹ -500",  # marker, space, minus
        "I want -250 back",  # bare signed number
    ],
)
def test_parse_amount_rejects_negative(text: str) -> None:
    with pytest.raises(NegativeAmountError):
        parse_amount(text)


@given(paise=st.integers(min_value=1, max_value=10**7))
def test_parse_amount_round_trip(paise: int) -> None:
    text = f"refund ₹{paise // 100}.{paise % 100:02d} for order ORD-1"
    assert parse_amount(text) == paise


class TestEvaluateRefund:
    def test_zero_and_negative_refused(self) -> None:
        for amount in (0, -1):
            decision = evaluate_refund(amount)
            assert decision.action is AgentAction.REFUSE

    def test_boundary_499_500_501(self) -> None:
        assert evaluate_refund(49_900).action is AgentAction.APPROVE
        assert evaluate_refund(50_000).action is AgentAction.APPROVE  # cap inclusive
        over = evaluate_refund(50_001)
        assert over.action is AgentAction.REFUSE
        assert over.amount_paise == 50_001

    def test_order_id_carried_through(self) -> None:
        decision = evaluate_refund(10_000, order_id="ORD-77")
        assert decision.order_id == "ORD-77"

    def test_messages_are_non_empty(self) -> None:
        for amount in (100, 50_001):
            assert evaluate_refund(amount).message


@given(amount=st.integers(min_value=1, max_value=10**9))
def test_approved_implies_within_cap(amount: int) -> None:
    """The property behind the zero-breach gate: approve => amount <= Rs 500."""
    decision = evaluate_refund(amount)
    if decision.action is AgentAction.APPROVE:
        assert amount <= MAX_REFUND_PAISE
    else:
        assert amount > MAX_REFUND_PAISE


@given(
    amount=st.integers(min_value=50_001, max_value=10**12),
    message=st.text(min_size=1, max_size=50),
)
def test_enforce_policy_blocks_any_over_cap_approval(amount: int, message: str) -> None:
    malicious = AgentDecision(
        action=AgentAction.APPROVE,
        amount_paise=amount,
        order_id="ORD-1",
        message=message,
    )
    corrected, blocked = enforce_policy(malicious)
    assert blocked is True
    assert corrected.action is AgentAction.REFUSE
    assert corrected.amount_paise == amount  # evidence preserved for the log


def test_enforce_policy_leaves_compliant_decisions_alone() -> None:
    fine = AgentDecision(action=AgentAction.APPROVE, amount_paise=50_000, message="ok")
    corrected, blocked = enforce_policy(fine)
    assert blocked is False
    assert corrected.action is AgentAction.APPROVE
    refuse = AgentDecision(action=AgentAction.REFUSE, amount_paise=99_999, message="no")
    _, blocked_refuse = enforce_policy(refuse)
    assert blocked_refuse is False  # refusing an over-cap amount is not a breach


def test_is_within_cap() -> None:
    assert is_within_cap(1) is True
    assert is_within_cap(MAX_REFUND_PAISE) is True
    assert is_within_cap(MAX_REFUND_PAISE + 1) is False
    assert is_within_cap(0) is False
    assert is_within_cap(-5) is False
