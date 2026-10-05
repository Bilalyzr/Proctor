"""Rank-2 prompt tests: metamorphic relations (blueprint Domain 1).

Paraphrasing a refund request, or swapping the customer's name, must not
change the decision - the invariant is the amount, not the phrasing.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.l2

PARAPHRASES = [
    "refund ₹300 for the broken mug",
    "I need my ₹300 back for the broken mug",
    "Can you refund 300 rupees? The mug arrived broken.",
    "Please process a refund of Rs.300 - the mug was broken on arrival.",
    "The mug came broken; refund INR 300.",
    "requesting ₹300 refund (broken mug)",
    "Hey, that mug was shattered. ₹300 refund please.",
    "I'd like ₹300 back for the damaged mug.",
    "refund the 300 I paid for the broken mug",
    "broken mug -> refund ₹300. thanks.",
]

NAME_SWAPS = [
    ("Asha", "refund ₹300 for my order"),
    ("Rahul", "refund ₹300 for my order"),
    ("Priya", "refund ₹300 for my order"),
]


@pytest.mark.parametrize("text", PARAPHRASES)
def test_paraphrase_invariance(assistant, text: str) -> None:
    turn = assistant.handle(text, order_id="ORD-M1")
    assert turn.decision.action.value == "approve"
    assert turn.decision.amount_paise == 30_000


def test_paraphrase_produces_identical_decisions(assistant) -> None:
    import json

    decisions = {
        json.dumps(
            assistant.handle(text, order_id="ORD-M1").decision.model_dump(exclude={"message"}),
            sort_keys=True,
        )
        for text in PARAPHRASES
    }
    assert len(decisions) == 1  # action + amount + order identical across rephrasings


@pytest.mark.parametrize(("name", "text"), NAME_SWAPS)
def test_name_swap_invariance(assistant, name: str, text: str) -> None:
    turn = assistant.handle(f"Hi, I'm {name}. {text}", order_id="ORD-M2")
    assert turn.decision.action.value == "approve"
    assert turn.decision.amount_paise == 30_000


def test_name_swaps_identical_decisions(assistant) -> None:
    decisions = {
        assistant.handle(
            f"Hi, I'm {name}. refund ₹300 for my order", order_id="ORD-M2"
        ).decision.amount_paise
        for name, _ in NAME_SWAPS
    }
    assert decisions == {30_000}
