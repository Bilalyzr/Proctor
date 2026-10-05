"""Data-loss prevention (SEC-3 / PRD-1): PII + financial masking, outbound.

Pattern-based with Luhn validation for card numbers (so test card numbers
that fail Luhn are not over-masked - false positives matter). Presidio slots
in behind the same interface when installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


PATTERNS: list[tuple[str, re.Pattern[str], bool]] = [
    # (rule, pattern, requires_luhn)
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"), False),
    ("phone-in", re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)"), False),
    ("card-pan", re.compile(r"\b(?:\d[ -]?){13,19}\b"), True),
    (
        "aadhaar-like",
        re.compile(r"(?<!\d)(?<!\d )\d{4}\s\d{4}\s\d{4}(?!\d)(?!\s\d)"),
        False,
    ),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), False),
]

CONFIDENTIAL_KEYWORDS = (
    "internal only",
    "confidential",
    "do not share",
    "salary",
    "audit unreleased",
    "pan number",
)

_MASKS: dict[str, str] = {
    "email": "[email-masked]",
    "phone-in": "[phone-masked]",
    "card-pan": "[card-masked]",
    "aadhaar-like": "[id-masked]",
    "ipv4": "[ip-masked]",
}


@dataclass(slots=True)
class MaskResult:
    """Outcome of masking one text."""

    text: str
    masked: bool
    findings: list[dict[str, str]] = field(default_factory=list)
    engine: str = "regex-dlp-v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "masked": self.masked,
            "findings": self.findings,
            "engine": self.engine,
        }


class DLPGuardrail:
    """Outbound masking on RAG context and model output.

    ``extra_patterns`` lets domain packs add vertical-specific detectors
    (PHI, student IDs, ops secrets) as ``(rule, regex, mask)`` triples.
    """

    engine = "regex-dlp-v1"

    def __init__(
        self,
        extra_keywords: tuple[str, ...] = (),
        extra_patterns: list[tuple[str, re.Pattern[str], str]] | None = None,
    ) -> None:
        self.keywords = tuple(k.lower() for k in CONFIDENTIAL_KEYWORDS + extra_keywords)
        self.domain_patterns = list(extra_patterns or [])

    def inspect(self, text: str) -> list[dict[str, str]]:
        """List findings without changing the text."""
        findings: list[dict[str, str]] = []
        for rule, pattern, needs_luhn in PATTERNS:
            for match in pattern.finditer(text):
                fragment = match.group(0)
                if needs_luhn:
                    digits = re.sub(r"\D", "", fragment)
                    if len(digits) < 13 or not _luhn_ok(digits):
                        continue  # not a real PAN: avoid false positives
                findings.append({"rule": f"dlp:{rule}", "fragment": fragment[:6] + "..."})
        lowered = text.lower()
        for keyword in self.keywords:
            if keyword in lowered:
                findings.append({"rule": "dlp:confidential", "fragment": keyword})
        for rule, pattern, _ in self.domain_patterns:
            for match in pattern.finditer(text):
                findings.append({"rule": f"dlp:{rule}", "fragment": match.group(0)[:6] + "..."})
        return findings

    def mask(self, text: str) -> MaskResult:
        """Mask PII / financial data; returns the cleaned text and findings."""
        findings = self.inspect(text)
        cleaned = text
        for rule, pattern, needs_luhn in PATTERNS:

            def replace(match: re.Match[str], _rule: str = rule, _luhn: bool = needs_luhn) -> str:
                if _luhn:
                    digits = re.sub(r"\D", "", match.group(0))
                    if len(digits) < 13 or not _luhn_ok(digits):
                        return match.group(0)
                return _MASKS[_rule]

            cleaned = pattern.sub(replace, cleaned)
        for _rule, pattern, mask in self.domain_patterns:
            cleaned = pattern.sub(mask, cleaned)
        for keyword in self.keywords:
            if keyword in cleaned.lower():
                cleaned = re.sub(re.escape(keyword), "[confidential-masked]", cleaned, flags=re.I)
        return MaskResult(
            text=cleaned,
            masked=bool(findings),
            findings=findings,
        )

    @staticmethod
    def presidio_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("presidio_analyzer") is not None
