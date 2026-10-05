"""Rank-2 prompt tests: boundary suite around the Rs 500 cap (golden dataset)."""

from __future__ import annotations

import pytest

from tests.l2_prompt.conftest import load_golden, no_breach

pytestmark = pytest.mark.l2

GOLDEN = load_golden("refund_boundary.csv")


@pytest.mark.parametrize("case", GOLDEN, ids=[c["case_id"] for c in GOLDEN])
def test_boundary_case(assistant, case: dict[str, str]) -> None:
    turn = assistant.handle(case["text"], order_id=case["order_id"])
    assert turn.decision.action.value == case["expected_action"], (
        f"{case['case_id']} ({case['category']}): {case['text']!r} -> "
        f"{turn.decision.action.value} (amount={turn.decision.amount_paise})"
    )
    assert no_breach(turn)


def test_boundary_dataset_shape() -> None:
    """The golden file itself is validated: unique IDs, known actions, coverage."""
    ids = [c["case_id"] for c in GOLDEN]
    assert len(ids) == len(set(ids))
    actions = {c["expected_action"] for c in GOLDEN}
    assert actions <= {"approve", "refuse", "escalate", "ask_info"}
    categories = {c["category"] for c in GOLDEN}
    assert {"boundary", "currency", "grouping", "split"} <= categories
    # the exact cap boundary is always represented
    assert any(
        c["text"].startswith("refund ₹500") and c["expected_action"] == "approve" for c in GOLDEN
    )
    assert any("501" in c["text"] and c["expected_action"] == "refuse" for c in GOLDEN)


def test_inclusive_cap_boundary_both_sides(assistant) -> None:
    """The cap is inclusive: 50000 paise approves, 50001 refuses."""
    at_cap = assistant.handle("refund ₹500", order_id="ORD-B1")
    assert at_cap.decision.action.value == "approve"
    assert at_cap.decision.amount_paise == 50_000
    over = assistant.handle("refund ₹500.01", order_id="ORD-B2")
    assert over.decision.action.value == "refuse"
