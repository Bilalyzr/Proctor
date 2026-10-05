"""E-commerce domain pack: wraps the existing refund-assistant reference SUT."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from domains.base import DomainFacts, DomainPack
from sut.policy import MAX_REFUND_PAISE, AmountParsingError, enforce_policy, parse_amount
from sut.prompts import SYSTEM_PROMPT
from sut.schemas import AgentDecision

REPO_ROOT = Path(__file__).resolve().parents[1]


class RefundFacts(DomainFacts):
    amount_paise: int | None = None
    order_id: str | None = None


def _parse(text: str, context: dict[str, Any]) -> RefundFacts:
    try:
        amount = parse_amount(text)
    except AmountParsingError:
        amount = None
    return RefundFacts(
        text=text,
        amount_paise=amount,
        order_id=(context.get("order_id") or None),
        authorized=bool(context.get("order_id")),
        wants_records=False,
    )


def _evaluate(facts: DomainFacts) -> AgentDecision:
    from sut.policy import evaluate_refund

    assert isinstance(facts, RefundFacts)
    return evaluate_refund(facts.amount_paise or 0)


def _enforce(decision: BaseModel, facts: DomainFacts) -> tuple[BaseModel, bool]:
    assert isinstance(decision, AgentDecision)
    return enforce_policy(decision)


def _persona(facts: DomainFacts) -> dict[str, Any]:
    assert isinstance(facts, RefundFacts)
    if facts.amount_paise is None or not facts.order_id:
        action, amount = "ask_info", None
    elif facts.amount_paise <= MAX_REFUND_PAISE:
        action, amount = "approve", facts.amount_paise
    else:
        action, amount = "refuse", facts.amount_paise
    return {
        "action": action,
        "amount_paise": amount,
        "order_id": facts.order_id,
        "message": "Handled per policy.",
    }


def build_ecommerce_pack() -> DomainPack:
    return DomainPack(
        id="ecommerce",
        display_name="E-commerce (refund assistant)",
        policy=type(
            "RefundPolicy",
            (),
            {
                "parse": staticmethod(_parse),
                "evaluate": staticmethod(_evaluate),
                "enforce": staticmethod(_enforce),
            },
        )(),
        schema=AgentDecision,
        system_prompt=SYSTEM_PROMPT,
        persona=_persona,
        golden_csv=REPO_ROOT / "datasets" / "golden" / "refund_golden.csv",
        risk_note="Financial: zero-breach gate on the Rs 500 cap.",
    )
