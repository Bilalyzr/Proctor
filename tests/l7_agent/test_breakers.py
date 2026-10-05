"""Rank-7 agentic tests: all four circuit breakers trigger at their bounds."""

from __future__ import annotations

import pytest

from breakers import AGENT_STEP_BUDGET, BreakerMonitor, BreakerTrip

pytestmark = [pytest.mark.l7, pytest.mark.nightly]


def test_agt1_recursion_limit_trips_at_depth_cap() -> None:
    """AGT-1: self-referencing plans end at the cap with an explanation."""
    monitor = BreakerMonitor(max_recursion_depth=3)
    with pytest.raises(BreakerTrip, match="recursion") as exc_info:
        for _ in range(10):
            monitor.enter("self-referencing plan")
    assert "depth cap (3)" in str(exc_info.value)
    assert exc_info.value.kind == "recursion"
    monitor.exit()
    assert monitor.depth == 3  # three nested enters unwound by one exit


def test_agt2_identical_state_repeats_terminate() -> None:
    """AGT-2: second identical state trips the deterministic breaker."""
    monitor = BreakerMonitor(max_identical_states=2)
    state = {"pending": "lookup", "order": "ORD-1", "last": "same-result"}
    monitor.observe_state(state)  # first occurrence
    with pytest.raises(BreakerTrip, match="state_repeat"):
        monitor.observe_state(state)  # identical -> trip
    different = {"pending": "lookup", "order": "ORD-1", "last": "other-result"}
    monitor.observe_state(different)  # no trip: state changed


def test_agt3_duplicate_successful_call_blocked_failed_retryable() -> None:
    """AGT-3: same tool + arguments; success blocks the repeat, failure doesn't."""
    monitor = BreakerMonitor()
    args = {"order_id": "ORD-1001"}
    call_hash = monitor.check_tool_call("order_lookup", args)
    monitor.check_tool_call("order_lookup", args)  # not yet successful: allowed
    monitor.register_success(call_hash)
    with pytest.raises(BreakerTrip, match="duplicate_call"):
        monitor.check_tool_call("order_lookup", args)
    other = monitor.check_tool_call("order_lookup", {"order_id": "ORD-1002"})
    assert other != call_hash  # different arguments: a different call


def test_agt4_step_budget_ends_run_at_ten_steps() -> None:
    """AGT-4: unsolvable task ends at the budget with a clear message."""
    monitor = BreakerMonitor(step_budget=AGENT_STEP_BUDGET)
    for _ in range(AGENT_STEP_BUDGET):
        monitor.step()
    assert monitor.steps == AGENT_STEP_BUDGET
    with pytest.raises(BreakerTrip, match="step_budget") as exc_info:
        monitor.step()
    assert "no further spend" in str(exc_info.value)


def test_monitor_summary_reports_trip_log() -> None:
    import contextlib

    monitor = BreakerMonitor(step_budget=1)
    monitor.step()
    with contextlib.suppress(BreakerTrip):
        monitor.step()
    summary = monitor.summary()
    assert summary["steps"] == 2
    assert summary["trips"] and "step_budget" in summary["trips"][0]


def test_agent_ends_pathological_loops_with_breaker() -> None:
    """An agent stuck repeating successful tool calls is stopped, not hung."""
    from sut.agent_loop import AgentRunResult, PlannerDecision, RefundAgent
    from sut.tools.base import RefundLedger, build_default_registry, load_orders

    class LoopPlanner:
        def next(self, state, step: int) -> PlannerDecision:
            return PlannerDecision(
                kind="call_tool",
                tool="order_lookup",
                arguments={"order_id": "ORD-1001"},
                final=False,
            )

    registry = build_default_registry(orders=load_orders(), ledger=RefundLedger())
    agent = RefundAgent(planner=LoopPlanner(), registry=registry)
    result = agent.run("refund ₹300", order_id="ORD-1001")
    assert result.status == "stopped_by_breaker"
    assert any("duplicate_call" in trip for trip in result.breaker_trips)
    assert "human will follow up" in result.final_message
    assert isinstance(result, AgentRunResult)
