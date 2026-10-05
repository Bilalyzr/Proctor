"""Synthetic case generation (AST-3): taxonomy-driven, seeded, schema-validated.

Offline, the combinatorial generator stands in for LLM generation (the same
interface a Claude/Copilot generator implements behind ``CaseGenerator``); with
a real provider the identical pipeline scales to the 100k-case weekly run.
"""

from __future__ import annotations

import random
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from sut.policy import MAX_REFUND_PAISE
from synthetic.taxonomy import Taxonomy, TaxonomySampler

VALID_ACTIONS = ("approve", "refuse", "escalate", "ask_info")


class GeneratedCase(BaseModel):
    """One synthetic test case (the schema validators enforce AST-3 quality)."""

    case_id: str
    text: str = Field(min_length=1, max_length=2000)
    order_id: str | None = Field(default=None, pattern=r"^ORD-\d{3,8}$")
    expected_action: str
    category: str
    amount_paise: int | None = Field(default=None, ge=0)
    intent: str
    persona: str
    seed: int = 1

    @model_validator(mode="after")
    def _validate(self) -> GeneratedCase:
        if self.expected_action not in VALID_ACTIONS:
            raise ValueError(f"expected_action must be one of {VALID_ACTIONS}")
        if (
            self.intent == "refund_request"
            and self.order_id is None
            and self.expected_action == "approve"
        ):
            raise ValueError("refund_request cases need an order_id to reach approve")
        return self


class CaseGenerator(Protocol):
    def generate(self, count: int) -> list[GeneratedCase]: ...


class TaxonomyCaseGenerator:
    """Deterministic combinatorial generator over the seed taxonomy."""

    def __init__(self, taxonomy: Taxonomy, *, seed: int = 42) -> None:
        self.sampler = TaxonomySampler(taxonomy, seed=seed)
        self.taxonomy = taxonomy
        self.rng = random.Random(seed)

    def generate(self, count: int) -> list[GeneratedCase]:
        """Generate ``count`` cases spanning intents, personas and boundaries."""
        if count < 1:
            raise ValueError("count must be >= 1")
        cases: list[GeneratedCase] = []
        boundary = self.taxonomy.amounts_paise["boundary"]
        while len(cases) < count:
            intent = self._pick_intent(len(cases), count)
            persona = self.rng.choice(self.taxonomy.personas)
            order_seed = self.rng.randint(1000, 999_999)
            if intent == "policy_question":
                question = self.sampler.sample_policy_question()
                cases.append(
                    GeneratedCase(
                        case_id=f"syn-{len(cases) + 1:06d}",
                        text=question,
                        order_id=None,
                        expected_action="ask_info",
                        category="policy_question",
                        amount_paise=None,
                        intent=intent,
                        persona=persona,
                        seed=self.rng.randint(1, 10**6),
                    )
                )
                continue
            amount = boundary[(len(cases) + self.rng.randint(0, 3)) % len(boundary)]
            framing = "override" if intent == "abuse_attempt" else None
            text, category = self.sampler.sample_refund_text(amount, framing_category=framing)
            expected = self._expected_action(amount)
            cases.append(
                GeneratedCase(
                    case_id=f"syn-{len(cases) + 1:06d}",
                    text=text,
                    order_id=f"ORD-{order_seed}",
                    expected_action=expected,
                    category=category,
                    amount_paise=amount,
                    intent=intent,
                    persona=persona,
                    seed=self.rng.randint(1, 10**6),
                )
            )
        return cases

    def _pick_intent(self, index: int, total: int) -> str:
        """Rotate intents so every intent is represented in any size run."""
        rotation = ["refund_request", "refund_request", "abuse_attempt", "policy_question"]
        return rotation[index % len(rotation)]

    def _expected_action(self, amount_paise: int) -> str:
        """Expected action is the POLICY answer, not a tone judgment: an
        abuse-framed request for a within-cap amount is still approved (the
        safety invariant is the cap, not the phrasing)."""
        if amount_paise <= MAX_REFUND_PAISE:
            return "approve"
        return "refuse"


def expected_capacity(taxonomy: Taxonomy) -> int:
    """The full combinatorial space the taxonomy can express."""
    framings = sum(len(v) for v in taxonomy.framings.values())
    refund_intents = max(1, len(taxonomy.intents) - 1)  # policy_question is separate
    return (
        len(taxonomy.amounts_paise["boundary"])
        * framings
        * len(taxonomy.reasons)
        * len(taxonomy.amounts_paise["currency_styles"])
        * len(taxonomy.personas)
        * refund_intents
    )
