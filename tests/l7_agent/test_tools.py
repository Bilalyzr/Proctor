"""Rank-7 agentic tests: the three SUT tools (task completion substrate)."""

from __future__ import annotations

import json

import pytest

from sut.policy import MAX_REFUND_PAISE
from sut.tools.base import RefundLedger, ToolResult, build_default_registry, load_orders

pytestmark = [pytest.mark.l7, pytest.mark.nightly]


def test_registry_exposes_three_tools_with_schemas(registry) -> None:
    names = [spec.name for spec in registry.list_tools()]
    assert names == ["escalate_to_human", "issue_refund", "order_lookup"]
    for spec in registry.list_tools():
        assert spec.description and spec.input_schema["type"] == "object"


def test_order_lookup_found_and_missing(registry) -> None:
    ok = registry.call("order_lookup", {"order_id": "ORD-1001"})
    assert ok.ok and ok.payload["customer"] == "Asha" and ok.payload["total_paise"] == 125_000
    missing = registry.call("order_lookup", {"order_id": "ORD-9999"})
    assert missing.is_error and "not found" in missing.error


def test_issue_refund_respects_cap_in_tool(registry) -> None:
    """Policy under autonomy: the tool itself refuses over-cap refunds."""
    over = registry.call("issue_refund", {"order_id": "ORD-1001", "amount_paise": 60_000})
    assert over.is_error and "cap" in over.error
    within = registry.call("issue_refund", {"order_id": "ORD-1001", "amount_paise": 50_000})
    assert within.ok and within.payload["amount_paise"] == 50_000


def test_issue_refund_enforces_cumulative_cap_per_order(registry) -> None:
    registry.call("issue_refund", {"order_id": "ORD-2001", "amount_paise": 30_000})
    second = registry.call("issue_refund", {"order_id": "ORD-2001", "amount_paise": 25_000})
    assert second.is_error and "cumulative" in second.error
    assert registry.ledger.total_for("ORD-2001") == 30_000


def test_issue_refund_rejects_ineligible_orders(registry) -> None:
    cancelled = registry.call("issue_refund", {"order_id": "ORD-3001", "amount_paise": 100})
    assert cancelled.is_error and "not eligible" in cancelled.error
    digital = registry.call("issue_refund", {"order_id": "ORD-4001", "amount_paise": 100})
    assert digital.is_error


def test_escalate_creates_ticket(registry) -> None:
    result = registry.call("escalate_to_human", {"reason": "legal threat", "order_id": "ORD-1001"})
    assert result.ok and result.payload["ticket_id"].startswith("ESC-")
    assert registry.escalations[0]["status"] == "open"


def test_unknown_tool_raises_key_error(registry) -> None:
    with pytest.raises(KeyError):
        registry.call("no_such_tool", {})


def test_duplicate_registration_rejected() -> None:
    reg = build_default_registry(orders={}, ledger=RefundLedger())
    spec = reg.spec("order_lookup")
    with pytest.raises(ValueError, match="already registered"):
        reg.register(spec, lambda args: ToolResult.success({}))


def test_orders_fixture_is_valid_json_with_expected_shape() -> None:
    orders = load_orders()
    parsed = json.loads(json.dumps(orders))
    assert parsed["ORD-1001"]["total_paise"] == 125_000
    assert all("ORD-" in key for key in orders)
    assert MAX_REFUND_PAISE == 50_000
