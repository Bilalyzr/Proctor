"""Refund policy engine: the hard Rs 500 cap (blueprint Section 1/Section 8).

Pure, deterministic logic - the most heavily unit-tested module in the repo
(negative, zero, non-numeric, boundary 499/500/501, currency variants) and the
subject of the Phase 2 property/metamorphic suites. Amounts are paise integers.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sut.schemas import AgentAction, AgentDecision

MAX_REFUND_PAISE = 50_000  # Rs 500 in paise

# Two-pass amount extraction: currency-marked amounts win over bare numbers,
# so "refund ₹250 for order 2024" picks 250, not 2024. Grouping supports Indian
# (1,20,000) and western (120,000) styles; decimals round half-up to paise.
_CURRENCY_AMOUNT_RE = re.compile(
    r"(?<![\w])(?:₹|rs\.?|inr)\s*"
    r"(?P<sign>-)?"
    r"(?P<number>\d{1,3}(?:,\d{2,3})+|\d+)"
    r"(?:\.(?P<frac>\d+))?",
    re.IGNORECASE,
)
_BARE_AMOUNT_RE = re.compile(
    r"(?<![\w.,-])(?P<sign>-)?(?P<number>\d{1,3}(?:,\d{2,3})+|\d+)"
    r"(?:\.(?P<frac>\d+))?(?![\d,])",
)

_INVALID_TEMPLATE = "cannot parse a refund amount from {input!r}"


class AmountParsingError(ValueError):
    """The user's message contains no usable refund amount."""


class NegativeAmountError(AmountParsingError):
    """The parsed amount is negative."""


def parse_amount(text: str) -> int:
    """Extract the refund amount (paise) from free text.

    Accepts "Rs 500", "₹1,200.50", "INR 499", "500", "rs. 499.99".
    Raises :class:`NegativeAmountError` for minus-signed amounts and
    :class:`AmountParsingError` when no amount is found.
    """
    match = _CURRENCY_AMOUNT_RE.search(text or "") or _BARE_AMOUNT_RE.search(text or "")
    if match is None:
        raise AmountParsingError(_INVALID_TEMPLATE.format(input=text))
    if match.group("sign"):
        raise NegativeAmountError(f"negative amount in {text!r}")
    whole = match.group("number").replace(",", "")
    frac = match.group("frac") or "0"
    try:
        rupees = Decimal(f"{whole}.{frac}")
    except InvalidOperation as exc:  # pragma: no cover - regex guarantees digits
        msg = _INVALID_TEMPLATE.format(input=text)
        raise AmountParsingError(msg) from exc
    paise = (rupees * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(paise)


def is_within_cap(amount_paise: int) -> bool:
    """True when the amount is at or under the Rs 500 cap."""
    return 0 < amount_paise <= MAX_REFUND_PAISE


def evaluate_refund(amount_paise: int, *, order_id: str | None = None) -> AgentDecision:
    """Pure policy decision for a parsed amount (used by tests and tools)."""
    if amount_paise <= 0:
        return AgentDecision(
            action=AgentAction.REFUSE,
            amount_paise=None,
            order_id=order_id,
            message="The refund amount must be a positive value, so I can't process this request.",
        )
    if amount_paise <= MAX_REFUND_PAISE:
        return AgentDecision(
            action=AgentAction.APPROVE,
            amount_paise=amount_paise,
            order_id=order_id,
            message=f"Approved: a refund of {_fmt(amount_paise)} will be issued.",
        )
    return AgentDecision(
        action=AgentAction.REFUSE,
        amount_paise=amount_paise,
        order_id=order_id,
        message=(
            f"I'm sorry, refunds above {_fmt(MAX_REFUND_PAISE)} need human approval. "
            "Would you like me to escalate this to a human agent?"
        ),
    )


def enforce_policy(decision: AgentDecision) -> tuple[AgentDecision, bool]:
    """Code-side guard: no approve above the cap, ever.

    Returns the (possibly corrected) decision and whether a breach was blocked.
    This runs *after* the model, so even a jailbroken or hallucinating model
    cannot push an over-cap approval through the assistant.
    """
    amount = decision.amount_paise
    if decision.action is AgentAction.APPROVE and amount is not None and amount > MAX_REFUND_PAISE:
        corrected = AgentDecision(
            action=AgentAction.REFUSE,
            amount_paise=amount,
            order_id=decision.order_id,
            message=(
                "Policy override applied: refunds above "
                f"{_fmt(MAX_REFUND_PAISE)} cannot be approved automatically."
            ),
        )
        return corrected, True
    return decision, False


def _fmt(amount_paise: int) -> str:
    rupees = amount_paise / 100.0
    text = f"{rupees:.2f}".rstrip("0").rstrip(".")
    return f"\u20b9{text}"
