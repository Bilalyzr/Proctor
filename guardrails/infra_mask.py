"""Infrastructure exposure protection (SEC-2): keys, private paths, ports.

Outbound: masks API-key shapes, Windows/UNC/private POSIX paths and port
signatures before anything reaches a user or a log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

INFRA_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "[key-masked]"),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[key-masked]"),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[key-masked]"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "[key-masked]"),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9-]{20,}\b"), "[key-masked]"),
    ("windows-path", re.compile(r"\b[A-Za-z]:\\Users?\\[^\s\"']+", re.I), "[path-masked]"),
    ("home-path", re.compile(r"(?<![\w])/(?:home|root)/[^\s\"']+"), "[path-masked]"),
    ("unc-path", re.compile(r"\\\\[A-Za-z0-9_.-]+\\[^\s\"']+"), "[path-masked]"),
    (
        "port-sig",
        re.compile(r"\b(?:port|listen(?:ing)?\s+on)\s*:?\s*(?:23|445|3389|5900|6379|9200)\b", re.I),
        "[port-masked]",
    ),
]


@dataclass(slots=True)
class InfraMaskResult:
    text: str
    masked: bool
    findings: list[dict[str, str]]

    def as_dict(self) -> dict[str, Any]:
        return {"masked": self.masked, "findings": self.findings}


class InfraMaskGuardrail:
    """Outbound masking of infrastructure exposure signatures."""

    engine = "regex-infra-v1"

    def inspect(self, text: str) -> list[dict[str, str]]:
        return [
            {"rule": f"infra:{rule}", "fragment": match.group(0)[:10] + "..."}
            for rule, pattern, _ in INFRA_RULES
            for match in pattern.finditer(text)
        ]

    def mask(self, text: str) -> InfraMaskResult:
        findings = self.inspect(text)
        cleaned = text
        for _rule, pattern, replacement in INFRA_RULES:
            cleaned = pattern.sub(replacement, cleaned)
        return InfraMaskResult(text=cleaned, masked=bool(findings), findings=findings)
