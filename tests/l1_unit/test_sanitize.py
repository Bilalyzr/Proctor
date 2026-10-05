"""Rank-1 unit tests: input sanitization (EVL-2 - control chars, size, markup)."""

from __future__ import annotations

import pytest

from sut.sanitize import TRUNCATION_MARKER, sanitize_input

pytestmark = pytest.mark.l1


def test_passes_clean_text_through() -> None:
    result = sanitize_input("I want a refund for order ORD-1001\nThanks")
    assert result.text == "I want a refund for order ORD-1001\nThanks"
    assert result.modified is False


def test_strips_control_characters() -> None:
    result = sanitize_input("re\x00fund\x1b now\x0b")
    assert result.text == "refund now"
    assert result.stripped_controls is True


def test_keeps_tab_and_newline() -> None:
    result = sanitize_input("line1\n\tline2")
    assert result.text == "line1\n\tline2"
    assert result.stripped_controls is False


def test_strips_zero_width_and_bidi() -> None:
    result = sanitize_input("re\u200bfund\u202e ok")
    assert result.text == "refund ok"


def test_normalizes_crlf() -> None:
    result = sanitize_input("a\r\nb\rc")
    assert result.text == "a\nb\nc"


def test_strips_markup_when_enabled() -> None:
    result = sanitize_input("<script>alert(1)</script> refund <b>₹400</b>")
    assert result.text == "alert(1) refund ₹400"
    assert result.stripped_markup is True


def test_keeps_markup_when_disabled() -> None:
    result = sanitize_input("5 < 6 and 6 > 5", strip_markup=False)
    assert result.text == "5 < 6 and 6 > 5"


def test_truncates_oversized_input() -> None:
    long_text = "x" * 100
    result = sanitize_input(long_text, max_chars=10)
    assert result.truncated is True
    assert result.text == "x" * 10 + TRUNCATION_MARKER


def test_empty_input_is_preserved_as_empty() -> None:
    result = sanitize_input("   ")
    assert result.text == "   "
    assert result.modified is False
