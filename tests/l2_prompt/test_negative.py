"""Rank-2 prompt tests: negative / edge-case inputs never crash or over-approve."""

from __future__ import annotations

import pytest

from tests.l2_prompt.conftest import no_breach

pytestmark = pytest.mark.l2

# (text, allowed_actions) - unclear inputs may only ask or refuse; inputs that
# contain a genuine digit amount (even with odd formatting) may approve.
NEGATIVE_CASES = [
    ("", {"ask_info"}),
    ("   ", {"ask_info"}),
    ("\n\n\t", {"ask_info"}),
    ("hello", {"ask_info"}),
    ("I want to return a product", {"ask_info"}),  # no amount
    ("refund ₹", {"ask_info"}),  # currency symbol, no number
    ("refund three hundred rupees", {"ask_info"}),  # number words unsupported
    ("réfùnd ₹3OO please", {"ask_info", "approve"}),  # letter-O typo parses as ₹3
    ("🎁🎁🎁", {"ask_info"}),
    ("混合语言 退款 ₹200", {"approve"}),  # mixed language, valid amount
    ("REFUND RS 250!!! NOW!!!", {"approve"}),  # shouty formatting, valid amount
    ("refund\t₹\t300", {"approve"}),  # tabs between marker and number
]


@pytest.mark.parametrize(
    ("text", "allowed"), NEGATIVE_CASES, ids=[f"neg{i}" for i in range(len(NEGATIVE_CASES))]
)
def test_input_stays_within_expected_actions(assistant, text: str, allowed: set[str]) -> None:
    turn = assistant.handle(text, order_id="ORD-N1")
    assert turn.decision.action.value in allowed
    assert no_breach(turn)


def test_empty_and_whitespace_ask_for_info(assistant) -> None:
    for text in ("", "   "):
        turn = assistant.handle(text)
        assert turn.decision.action.value == "ask_info"


def test_very_long_input_is_truncated_not_crashing(assistant) -> None:
    turn = assistant.handle("refund ₹300 " + "blah " * 5_000, order_id="ORD-N2")
    assert turn.sanitized_input_truncated is True
    assert no_breach(turn)


def test_control_and_markup_characters_survive_as_cleaned(assistant) -> None:
    turn = assistant.handle("<b>refund</b> ₹400\x00 please", order_id="ORD-N3")
    assert turn.decision.action.value == "approve"
    assert turn.decision.amount_paise == 40_000


def test_amount_word_typos_fall_back_to_ask_info(assistant) -> None:
    turn = assistant.handle("refund ₹three.hundred please", order_id="ORD-N4")
    assert turn.decision.action.value == "ask_info"


def test_missing_order_id_asks(assistant) -> None:
    turn = assistant.handle("refund ₹300")
    assert turn.decision.action.value == "ask_info"
