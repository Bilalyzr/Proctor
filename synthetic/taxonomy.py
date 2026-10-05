"""Taxonomy loading and case synthesis (seeded, combinatorial)."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class Taxonomy(BaseModel):
    """The human-owned seed taxonomy (GOV-1)."""

    version: int
    intents: list[str]
    personas: list[str]
    amounts_paise: dict[str, Any]
    reasons: list[str]
    framings: dict[str, list[str]]
    policy_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Taxonomy:
        if not self.intents:
            raise ValueError("taxonomy needs intents")
        if not {"boundary", "currency_styles"} <= set(self.amounts_paise):
            raise ValueError("taxonomy needs amounts_paise.boundary and .currency_styles")
        if not self.framings:
            raise ValueError("taxonomy needs framings")
        return self

    @classmethod
    def load(cls, path: str | Path) -> Taxonomy:
        raw: Any = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(raw)


def format_amount(paise: int, style: str) -> str:
    """Render paise with a taxonomy currency style."""
    rupees = paise / 100.0
    if style == "₹{r:.2f}":
        return f"₹{rupees:.2f}"
    rendered = f"{rupees:.2f}".rstrip("0").rstrip(".")
    return style.format(r=rendered)


class TaxonomySampler:
    """Seeded sampler over the taxonomy space."""

    def __init__(self, taxonomy: Taxonomy, seed: int = 42) -> None:
        self.taxonomy = taxonomy
        self.rng = random.Random(seed)

    def sample_refund_text(
        self, amount_paise: int, *, framing_category: str | None = None
    ) -> tuple[str, str]:
        """(text, framing_category) for one refund request."""
        category = framing_category or self.rng.choice(list(self.taxonomy.framings))
        template = self.rng.choice(self.taxonomy.framings[category])
        style = self.rng.choice(self.taxonomy.amounts_paise["currency_styles"])
        reason = self.rng.choice(self.taxonomy.reasons)
        text = template.format(amount=format_amount(amount_paise, style), reason=reason)
        return text, category

    def sample_policy_question(self) -> str:
        return self.rng.choice(self.taxonomy.policy_questions)
