"""Tool plumbing for the agentic SUT: specs, results, registry (MCP-1).

``issue_refund`` enforces the Rs 500 cap *in the tool itself*, including the
cumulative per-order total from the ledger - so even a rogue planner cannot
push money out (defense in depth with ``sut.policy`` and the agent guard).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from sut.policy import MAX_REFUND_PAISE

ORDERS_PATH = Path(__file__).resolve().parents[1] / "data" / "orders.json"


class ToolError(RuntimeError):
    """A tool execution failure (transported as isError=true over MCP)."""


class ToolResult(BaseModel):
    """Normalized tool outcome (content blocks mirror MCP structuredContent)."""

    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    is_error: bool = False  # MCP error transport: tool ran, execution failed

    @classmethod
    def success(cls, payload: dict[str, Any]) -> ToolResult:
        return cls(ok=True, payload=payload, is_error=False)

    @classmethod
    def failure(cls, message: str) -> ToolResult:
        return cls(ok=False, error=message, is_error=True)

    def to_mcp_content(self) -> list[dict[str, Any]]:
        """MCP content blocks: structured result or error text."""
        if self.is_error:
            return [{"type": "text", "text": f"tool error: {self.error}"}]
        return [{"type": "text", "text": json.dumps(self.payload, sort_keys=True, default=str)}]


class ToolSpec(BaseModel):
    """One tool definition exposed over MCP (with a JSON Schema)."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def to_mcp(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class RefundLedger:
    """In-memory refund ledger: cumulative cap enforcement per order."""

    def __init__(self) -> None:
        self._by_order: dict[str, list[int]] = {}

    def record(self, order_id: str, amount_paise: int) -> None:
        self._by_order.setdefault(order_id, []).append(amount_paise)

    def total_for(self, order_id: str) -> int:
        return sum(self._by_order.get(order_id, []))

    def entries(self, order_id: str) -> list[int]:
        return list(self._by_order.get(order_id, []))


def load_orders(path: Path = ORDERS_PATH) -> dict[str, dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


Handler = Callable[[dict[str, Any]], ToolResult]


class ToolRegistry:
    """Named tools with schemas; the agent and MCP server share one registry."""

    def __init__(
        self, orders: dict[str, Any] | None = None, ledger: RefundLedger | None = None
    ) -> None:
        self.orders = orders if orders is not None else load_orders()
        self.ledger = ledger if ledger is not None else RefundLedger()
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Handler] = {}
        self.escalations: list[dict[str, Any]] = []

    def register(self, spec: ToolSpec, handler: Handler) -> None:
        if spec.name in self._specs:
            msg = f"tool already registered: {spec.name}"
            raise ValueError(msg)
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def spec(self, name: str) -> ToolSpec:
        return self._specs[name]

    def list_tools(self) -> list[ToolSpec]:
        return [self._specs[name] for name in sorted(self._specs)]

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool: unknown tool is a protocol-level error (caller maps
        it to JSON-RPC -32602); in-tool failures return isError results."""
        handler = self._handlers.get(name)
        if handler is None:
            raise KeyError(name)
        return handler(arguments)


# ------------------------------------------------------------------- schemas
AMOUNT_FIELD = {
    "type": "integer",
    "minimum": 1,
    "description": "refund amount in paise (Rs 1 = 100)",
}
ORDER_ID_FIELD = {
    "type": "string",
    "pattern": "^ORD-[0-9]{3,8}$",
    "description": "customer order id, e.g. ORD-1001",
}

ORDER_LOOKUP_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"order_id": ORDER_ID_FIELD},
    "required": ["order_id"],
    "additionalProperties": False,
}
ISSUE_REFUND_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"order_id": ORDER_ID_FIELD, "amount_paise": AMOUNT_FIELD},
    "required": ["order_id", "amount_paise"],
    "additionalProperties": False,
}
ESCALATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        # optional context: a valid order id, or an explicit null
        "order_id": {
            "anyOf": [{"type": "string", "pattern": "^ORD-[0-9]{3,8}$"}, {"type": "null"}],
            "description": "optional order context",
        },
        "reason": {"type": "string", "minLength": 3, "maxLength": 500},
    },
    "required": ["reason"],
    "additionalProperties": False,
}


def build_default_registry(
    orders: dict[str, Any] | None = None, ledger: RefundLedger | None = None
) -> ToolRegistry:
    """The three SUT tools: order_lookup, issue_refund, escalate_to_human."""

    def order_lookup(args: dict[str, Any]) -> ToolResult:
        order_id = args["order_id"]
        record = registry.orders.get(order_id)
        if record is None:
            return ToolResult.failure(f"order {order_id} not found")
        return ToolResult.success({"order_id": order_id, **record})

    def issue_refund(args: dict[str, Any]) -> ToolResult:
        order_id = args["order_id"]
        amount = int(args["amount_paise"])
        record = registry.orders.get(order_id)
        if record is None:
            return ToolResult.failure(f"order {order_id} not found")
        if not record.get("eligible", False):
            return ToolResult.failure(f"order {order_id} is not eligible for refunds")
        if amount > MAX_REFUND_PAISE:
            return ToolResult.failure(
                f"refund of {amount} paise exceeds the Rs {MAX_REFUND_PAISE // 100} cap"
            )
        cumulative = registry.ledger.total_for(order_id) + amount
        if cumulative > MAX_REFUND_PAISE:
            return ToolResult.failure(
                f"cumulative refunds for {order_id} would reach {cumulative} paise, "
                f"above the Rs {MAX_REFUND_PAISE // 100} cap"
            )
        registry.ledger.record(order_id, amount)
        return ToolResult.success(
            {
                "refund_id": f"RF-{uuid4().hex[:10]}",
                "order_id": order_id,
                "amount_paise": amount,
                "remaining_budget_paise": MAX_REFUND_PAISE - registry.ledger.total_for(order_id),
            }
        )

    def escalate(args: dict[str, Any]) -> ToolResult:
        ticket = {
            "ticket_id": f"ESC-{uuid4().hex[:8]}",
            "reason": args["reason"],
            "order_id": args.get("order_id"),
            "status": "open",
        }
        registry.escalations.append(ticket)
        return ToolResult.success(ticket)

    registry = ToolRegistry(orders=orders, ledger=ledger)
    registry.register(
        ToolSpec(
            name="order_lookup",
            description="Look up a customer order by id: status, total, refund eligibility.",
            input_schema=ORDER_LOOKUP_SCHEMA,
        ),
        order_lookup,
    )
    registry.register(
        ToolSpec(
            name="issue_refund",
            description=(
                "Issue a refund for an order. Hard policy: single and cumulative "
                "refunds per order never exceed Rs 500 (50000 paise)."
            ),
            input_schema=ISSUE_REFUND_SCHEMA,
        ),
        issue_refund,
    )
    registry.register(
        ToolSpec(
            name="escalate_to_human",
            description=(
                "Escalate a case to a human agent (over-cap refunds, legal threats, edge cases)."
            ),
            input_schema=ESCALATE_SCHEMA,
        ),
        escalate,
    )
    return registry
