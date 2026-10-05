"""Brand safety (SEC-4): toxicity, policy violations, off-brand content.

Checked inbound (abusive users) and outbound (assistant replies), including
the shop-specific rule: replies must never promise refunds above the cap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

TOXIC_LEXICON = (
    "idiot",
    "stupid",
    "shut up",
    "moron",
    "loser",
    "scam artists",
    "thieves",
    "garbage company",
    "hate you",
)

COMPETITOR_TRASH_TALK = (
    "shopfast is a scam",
    "buy from competitor",
    "avoid shopfast",
)

OVER_PROMISE = re.compile(
    r"refund\s+(?:of\s+)?[₹rs.\s]*([5-9]\d{2,}|\d{4,})(\.\d+)?"
    r"\s*(?:has been approved|is approved|approved)",
    re.I,
)
CAP_MENTION = 500


@dataclass(slots=True)
class BrandVerdict:
    blocked: bool
    rule: str | None
    fragment: str | None = None
    engine: str = "lexicon-brand-v1"

    def as_dict(self) -> dict[str, Any]:
        return {"blocked": self.blocked, "rule": self.rule, "engine": self.engine}


class BrandSafetyGuardrail:
    """Inbound + outbound brand-safety checks."""

    engine = "lexicon-brand-v1"

    def inspect_inbound(self, text: str) -> BrandVerdict:
        lowered = text.lower()
        for term in TOXIC_LEXICON:
            if term in lowered:
                return BrandVerdict(True, "brand:toxicity-inbound", term)
        for term in COMPETITOR_TRASH_TALK:
            if term in lowered:
                return BrandVerdict(True, "brand:off-brand", term)
        return BrandVerdict(False, None)

    def inspect_outbound(self, text: str) -> BrandVerdict:
        lowered = text.lower()
        for term in TOXIC_LEXICON:
            if term in lowered:
                return BrandVerdict(True, "brand:toxicity-outbound", term)
        match = OVER_PROMISE.search(text)
        if match:
            try:
                rupees = float(match.group(1))
            except ValueError:  # pragma: no cover - regex guarantees digits
                rupees = 0.0
            if rupees > CAP_MENTION:
                return BrandVerdict(True, "brand:over-cap-promise", match.group(0)[:60])
        return BrandVerdict(False, None)
