"""Prompt-injection defense (SEC-1): direct and indirect pattern classifier.

Rule + pattern based, deterministic, with base64-blob heuristics for
obfuscated payloads. Heavy ML classifiers (Llama Guard, Lakera) slot in
behind the same interface; ``available()`` reports what is actually active so
reports never overstate the engine.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Any

INBOUND_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "override-ignore-previous",
        re.compile(
            r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts)", re.I
        ),
    ),
    (
        "override-system-role",
        re.compile(
            r"you\s+are\s+(now\s+)?(dan|an?\s+(unrestricted|unfiltered|jailbroken)\s+\w+)", re.I
        ),
    ),
    (
        "fake-system-directive",
        re.compile(r"(###\s*)?(system|institutional)\s*(override|directive|note)\s*[:>]", re.I),
    ),
    (
        "fake-system-tag",
        re.compile(r"(?<![a-z])system\s*[:>]", re.I),
    ),
    (
        "policy-forgery",
        re.compile(
            r"(new|updated)\s+(company\s+)?policy\b[^.]{0,80}"
            r"\b(pre-?approv|unlimited|no longer|bypass)",
            re.I,
        ),
    ),
    (
        "credential-exfil",
        re.compile(
            r"(reveal|print|show|repeat)\s+(your\s+)?(system\s+)?(prompt|instructions|api\s*key|secret)",
            re.I,
        ),
    ),
    (
        "instruction-in-doc",
        re.compile(
            r"\b(approve\s+all\s+refunds|disregard\s+the\s+cap|the\s+cap\s+is\s+now)\b", re.I
        ),
    ),
    ("delimiter-spoof", re.compile(r"</?(system|assistant|instructions?)>", re.I)),
]

_B64_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}")
_B64_TRIGGER_WORDS = ("approve", "refund", "ignore", "instruction", "policy", "cap")


@dataclass(slots=True)
class InjectionVerdict:
    """Classifier outcome for one text."""

    blocked: bool
    rule: str | None
    matched_fragment: str | None = None
    engine: str = "regex-classifier-v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "rule": self.rule,
            "matched_fragment": self.matched_fragment,
            "engine": self.engine,
        }


def _decode_base64_candidates(text: str) -> list[str]:
    """Decode plausible base64 blobs so obfuscated payloads can be matched."""
    decoded: list[str] = []
    for match in _B64_RE.findall(text):
        try:
            raw = base64.b64decode(match, validate=True)
            candidate = raw.decode("utf-8", errors="ignore")
        except (binascii.Error, ValueError):
            continue
        if candidate.isprintable() and any(w in candidate.lower() for w in _B64_TRIGGER_WORDS):
            decoded.append(candidate)
    return decoded


class InjectionGuardrail:
    """Inbound classifier: direct user text and indirect (retrieved) content."""

    engine = "regex-classifier-v1"

    def __init__(self, extra_rules: list[tuple[str, re.Pattern[str]]] | None = None) -> None:
        self.rules = list(INBOUND_RULES) + list(extra_rules or [])

    def inspect(self, text: str, *, source: str = "user") -> InjectionVerdict:
        """Classify one text; ``source`` labels direct ('user') vs indirect ('rag')."""
        for candidate in [text, *_decode_base64_candidates(text)]:
            for rule_name, pattern in self.rules:
                match = pattern.search(candidate)
                if match:
                    return InjectionVerdict(
                        blocked=True,
                        rule=f"injection:{rule_name}",
                        matched_fragment=match.group(0)[:80],
                    )
        return InjectionVerdict(blocked=False, rule=None)

    @staticmethod
    def ml_classifier_available() -> bool:
        """True when a heavy ML classifier is importable (never in offline CI)."""
        import importlib.util

        return (
            importlib.util.find_spec("llama_guard") is not None
            or importlib.util.find_spec("lakera") is not None
        )
