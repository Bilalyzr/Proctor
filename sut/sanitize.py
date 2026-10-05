"""Input sanitization for model prompts (EVL-2: versioned, explicit settings).

Blueprint Domain 2: control characters, oversized input and embedded markup
are cleaned or rejected before anything reaches the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# C0 controls except tab/newline/carriage-return, plus C1 range and DEL
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# zero-width and bidi-override characters (injection-relevant invisibles)
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
# angle-bracket tags (markup stripping; deliberately simple)
_TAG_RE = re.compile(r"<[^>\n]{0,200}>")

TRUNCATION_MARKER = "…[input truncated]"


@dataclass(frozen=True, slots=True)
class SanitizedInput:
    """Result of sanitization, with flags for telemetry and tests."""

    text: str
    truncated: bool
    stripped_controls: bool
    stripped_markup: bool

    @property
    def modified(self) -> bool:
        return truncated_or_cleaned(self)


def truncated_or_cleaned(sanitized: SanitizedInput) -> bool:
    return sanitized.truncated or sanitized.stripped_controls or sanitized.stripped_markup


def sanitize_input(
    text: str,
    *,
    max_chars: int = 8000,
    strip_markup: bool = True,
) -> SanitizedInput:
    """Clean user input before it enters a prompt.

    Removes control/invisible characters, optionally strips markup tags, and
    truncates to ``max_chars`` with an explicit marker. Empty/whitespace-only
    input is preserved as empty - the agent turns that into ask_info, not a loop.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _CONTROL_RE.sub("", normalized)
    stripped_controls = cleaned != normalized
    cleaned = _INVISIBLE_RE.sub("", cleaned)
    if strip_markup:
        before = cleaned
        cleaned = _TAG_RE.sub("", cleaned)
        stripped_markup = cleaned != before
    else:
        stripped_markup = False
    truncated = False
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + TRUNCATION_MARKER
        truncated = True
    return SanitizedInput(
        text=cleaned,
        truncated=truncated,
        stripped_controls=stripped_controls,
        stripped_markup=stripped_markup,
    )
