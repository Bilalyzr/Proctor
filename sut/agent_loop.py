"""The agentic refund loop (rank 7 SUT): plan -> tool -> observe -> respond.

Design notes:

* The ``Planner`` abstraction is where a model sits. ``RulePlanner`` is the
  deterministic offline planner (same protocol an LLM planner implements via a
  real provider); tests inject pathological planners to trigger breakers and
  failure injection.
* Every tool call passes through the :class:`~breakers.monitor.BreakerMonitor`
  (all four breakers) and the :class:`TokenLedger` records tokens per request
  *and* per tool (MCP-2).
* ``issue_refund`` enforces the cap in the tool + cumulative ledger, so policy
  holds even when a tool output or planner goes rogue (policy under autonomy).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from breakers import BreakerMonitor, BreakerTrip
from sut.policy import MAX_REFUND_PAISE, AmountParsingError, parse_amount
from sut.tools.base import ToolRegistry, ToolResult, build_default_registry

_ESCALATE_WORDS = re.compile(r"human|manager|escalate|legal|lawyer|police", re.IGNORECASE)


class TokenLedger:
    """MCP-2: token consumption per request and per tool."""

    def __init__(self) -> None:
        self.request_prompt = 0
        self.request_completion = 0
        self.per_tool: dict[str, dict[str, int]] = {}

    def record_request(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.request_prompt += prompt_tokens
        self.request_completion += completion_tokens

    def record_tool(self, tool: str, prompt_tokens: int, completion_tokens: int) -> None:
        entry = self.per_tool.setdefault(tool, {"prompt_tokens": 0, "completion_tokens": 0})
        entry["prompt_tokens"] += prompt_tokens
        entry["completion_tokens"] += completion_tokens

    def summary(self) -> dict[str, Any]:
        return {
            "request": {
                "prompt_tokens": self.request_prompt,
                "completion_tokens": self.request_completion,
                "total_tokens": self.request_prompt + self.request_completion,
            },
            "per_tool": {
                tool: counts
                | {"total_tokens": counts["prompt_tokens"] + counts["completion_tokens"]}
                for tool, counts in self.per_tool.items()
            },
        }


class PlannerDecision(BaseModel):
    """One planner step: respond to the user, or call a tool."""

    kind: Literal["respond", "call_tool"]
    message: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    final: bool = True


class AgentState(BaseModel):
    """Everything the planner sees for one request."""

    user_text: str
    order_id: str | None = None
    amount_paise: int | None = None
    history: list[dict[str, Any]] = []


class Planner(Protocol):
    def next(self, state: AgentState, step: int) -> PlannerDecision: ...


class RulePlanner:
    """Deterministic offline planner: the refund persona as an agent."""

    def next(self, state: AgentState, step: int) -> PlannerDecision:
        if state.amount_paise is None:
            return PlannerDecision(
                kind="respond",
                message="Could you share the refund amount (and your order ID)?",
            )
        if not state.order_id:
            return PlannerDecision(
                kind="respond", message="What is your order ID so I can look it up?"
            )
        last = state.history[-1] if state.history else None
        if step == 0 or last is None:
            return PlannerDecision(
                kind="call_tool",
                tool="order_lookup",
                arguments={"order_id": state.order_id},
                final=False,
            )
        if last and last.get("tool") == "order_lookup":
            if not last.get("ok"):
                return PlannerDecision(
                    kind="call_tool",
                    tool="escalate_to_human",
                    arguments={
                        "reason": f"order lookup failed: {last.get('error')}",
                        "order_id": state.order_id,
                    },
                )
            record = last.get("result", {})
            if not record.get("eligible", False):
                return PlannerDecision(
                    kind="respond",
                    message="I'm sorry, this order is not eligible for refunds.",
                )
            if state.amount_paise > MAX_REFUND_PAISE:
                if _ESCALATE_WORDS.search(state.user_text):
                    return PlannerDecision(
                        kind="call_tool",
                        tool="escalate_to_human",
                        arguments={
                            "reason": f"over-cap refund request ({state.amount_paise} paise)",
                            "order_id": state.order_id,
                        },
                    )
                return PlannerDecision(
                    kind="respond",
                    message=(
                        "Refunds above ₹500 need human approval; I can escalate if you'd like."
                    ),
                )
            return PlannerDecision(
                kind="call_tool",
                tool="issue_refund",
                arguments={"order_id": state.order_id, "amount_paise": state.amount_paise},
            )
        if last and last.get("tool") == "issue_refund":
            if last.get("ok"):
                payload = last.get("result", {})
                return PlannerDecision(
                    kind="respond",
                    message=(
                        f"Refund {payload.get('refund_id')} of ₹"
                        f"{(payload.get('amount_paise', 0)) / 100:.2f} approved."
                    ),
                )
            return PlannerDecision(
                kind="respond", message=f"I couldn't issue the refund: {last.get('error')}"
            )
        if last and last.get("tool") == "escalate_to_human":
            payload = last.get("result", {})
            return PlannerDecision(
                kind="respond",
                message=(
                    f"I've escalated this to a human ({payload.get('ticket_id')}); "
                    "expect a reply within 24 hours."
                ),
            )
        return PlannerDecision(kind="respond", message="Let me look into that.")


@dataclass(slots=True)
class AgentRunResult:
    """One agentic request's outcome, with trajectory and accounting."""

    final_message: str
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    breaker_trips: list[str] = field(default_factory=list)
    tokens: dict[str, Any] = field(default_factory=dict)
    tools_called: list[str] = field(default_factory=list)
    status: str = "completed"  # completed | stopped_by_breaker | failed

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "final_message": self.final_message,
            "tools_called": self.tools_called,
            "trajectory": self.trajectory,
            "breaker_trips": self.breaker_trips,
            "tokens": self.tokens,
        }


class RefundAgent:
    """The multi-step agent around a planner, a tool registry and breakers."""

    def __init__(
        self,
        planner: Planner | None = None,
        registry: ToolRegistry | None = None,
        *,
        max_tool_retries: int = 1,
    ) -> None:
        self.planner = planner if planner is not None else RulePlanner()
        self.registry = registry if registry is not None else build_default_registry()
        self.max_tool_retries = max_tool_retries

    def run(
        self,
        user_text: str,
        *,
        order_id: str | None = None,
        monitor: BreakerMonitor | None = None,
    ) -> AgentRunResult:
        monitor = monitor if monitor is not None else BreakerMonitor()
        ledger = TokenLedger()
        result = AgentRunResult(final_message="")
        try:
            amount = parse_amount(user_text)
        except AmountParsingError:
            amount = None
        state = AgentState(
            user_text=user_text,
            order_id=(order_id or "").strip() or None,
            amount_paise=amount,
        )
        ledger.record_request(len(user_text) // 4 + 8, 24)

        try:
            self._loop(state, monitor, ledger, result)
            result.status = "completed"
        except BreakerTrip as trip:
            result.breaker_trips.append(f"{trip.kind}: {trip.explanation}")
            result.status = "stopped_by_breaker"
            result.final_message = (
                f"I have to stop here - {trip.explanation} A human will follow up."
            )
        result.tokens = ledger.summary()
        return result

    # ------------------------------------------------------------------ loop
    def _loop(
        self,
        state: AgentState,
        monitor: BreakerMonitor,
        ledger: TokenLedger,
        result: AgentRunResult,
    ) -> None:
        for step in range(monitor.step_budget + 1):
            monitor.step()  # AGT-4 raises once the budget is exhausted
            monitor.observe_state(self._state_digest(state))  # AGT-2
            decision = self._plan(state, step, monitor)  # AGT-1 inside _plan
            if decision.kind == "respond":
                result.final_message = decision.message or ""
                return
            if decision.tool is None:
                continue
            tool = decision.tool
            arguments = decision.arguments or {}
            result.tools_called.append(tool)
            outcome = self._execute_tool(tool, arguments, monitor, ledger)
            state = state.model_copy(
                update={
                    "history": [
                        *state.history,
                        {
                            "tool": tool,
                            "ok": outcome.ok,
                            "result": outcome.payload,
                            "error": outcome.error,
                        },
                    ]
                }
            )
            result.trajectory.append(
                {
                    "step": step,
                    "action": f"call_tool:{tool}",
                    "arguments": arguments,
                    "ok": outcome.ok,
                    "result": outcome.payload,
                }
            )

    def _plan(self, state: AgentState, step: int, monitor: BreakerMonitor) -> PlannerDecision:
        monitor.enter("planning")
        try:
            return self.planner.next(state, step)
        finally:
            monitor.exit()

    def _execute_tool(
        self,
        tool: str,
        arguments: dict[str, Any],
        monitor: BreakerMonitor,
        ledger: TokenLedger,
    ) -> ToolResult:
        """Call a tool with duplicate-call protection and bounded retries.

        A *failed* attempt is retryable (AGT-3 blocks only repeats of
        successful calls); after ``max_tool_retries`` retries the last error
        is returned and the planner decides the fallback.
        """
        call_hash = monitor.check_tool_call(tool, arguments)  # AGT-3
        attempts = self.max_tool_retries + 1
        last_error: ToolResult | None = None
        for _ in range(attempts):
            outcome = self.registry.call(tool, arguments)
            ledger.record_tool(
                tool,
                len(str(arguments)) // 4 + 8,
                len(str(outcome.payload)) // 4 + 8,
            )
            if outcome.ok:
                monitor.register_success(call_hash)
                return outcome
            last_error = outcome
        assert last_error is not None
        return last_error

    def _state_digest(self, state: AgentState) -> dict[str, Any]:
        """State identity for AGT-2: same intent + same last observation.

        Deliberately excludes history length (always grows) and the tool name
        (the breaker must catch *observation* loops, not just call loops -
        repeated calls are AGT-3's job).
        """
        last = state.history[-1] if state.history else None
        return {
            "order_id": state.order_id,
            "amount_paise": state.amount_paise,
            "last_result": (last or {}).get("result"),
            "last_ok": (last or {}).get("ok"),
        }
