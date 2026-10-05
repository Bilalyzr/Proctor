"""Circuit breakers that stop runaway agents (AGT-1 .. AGT-4).

Four hard limits per session/request:

* **recursion** - hard cap on nested reasoning depth (AGT-1)
* **state repeat** - terminate when an identical state repeats (AGT-2)
* **duplicate call** - hash(tool name + arguments); block repeated identical
  *successful* calls (failed attempts may be retried once) (AGT-3)
* **step budget** - maximum operations per request (AGT-4, default 10)

Each trip carries the breaker kind and a human-readable explanation so the
session ends with a clear message and zero further spend.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

AGENT_STEP_BUDGET = 10

BreakerKind = Literal["recursion", "state_repeat", "duplicate_call", "step_budget"]


class BreakerTrip(RuntimeError):
    """A circuit breaker fired; the run must stop immediately."""

    def __init__(self, kind: BreakerKind, explanation: str) -> None:
        super().__init__(f"[{kind}] {explanation}")
        self.kind = kind
        self.explanation = explanation


@dataclass(slots=True)
class BreakerMonitor:
    """Tracks all four limits for one session/request."""

    max_recursion_depth: int = 8
    max_identical_states: int = 2
    step_budget: int = AGENT_STEP_BUDGET
    _depth: int = 0
    _steps: int = 0
    _state_counts: dict[str, int] = field(default_factory=dict)
    _successful_calls: set[str] = field(default_factory=set)
    trips: list[BreakerTrip] = field(default_factory=list)

    # ------------------------------------------------------------- recursion
    def enter(self, purpose: str = "reasoning") -> None:
        """AGT-1: nested reasoning depth cap."""
        self._depth += 1
        if self._depth > self.max_recursion_depth:
            trip = BreakerTrip(
                "recursion",
                f"nested {purpose} exceeded the depth cap "
                f"({self.max_recursion_depth}); stopping at depth {self._depth}",
            )
            self.trips.append(trip)
            raise trip

    def exit(self) -> None:
        self._depth = max(0, self._depth - 1)

    # ----------------------------------------------------------- state repeat
    def observe_state(self, state: dict[str, Any]) -> None:
        """AGT-2: terminate when the identical state repeats."""
        digest = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
        count = self._state_counts.get(digest, 0) + 1
        self._state_counts[digest] = count
        if count >= self.max_identical_states:
            trip = BreakerTrip(
                "state_repeat",
                f"identical agent state observed {count} times; deterministic "
                "circuit breaker engaged",
            )
            self.trips.append(trip)
            raise trip

    # --------------------------------------------------------- duplicate call
    def check_tool_call(self, tool: str, arguments: dict[str, Any]) -> str:
        """AGT-3: return the call hash; raise if this exact call already
        *succeeded* (failed attempts stay retryable)."""
        call_hash = hashlib.sha256(
            json.dumps({"tool": tool, "args": arguments}, sort_keys=True, default=str).encode()
        ).hexdigest()
        if call_hash in self._successful_calls:
            trip = BreakerTrip(
                "duplicate_call",
                f"identical call to {tool} with identical arguments was already "
                "completed; duplicate blocked",
            )
            self.trips.append(trip)
            raise trip
        return call_hash

    def register_success(self, call_hash: str) -> None:
        self._successful_calls.add(call_hash)

    # ------------------------------------------------------------ step budget
    def step(self) -> None:
        """AGT-4: maximum operations per request."""
        self._steps += 1
        if self._steps > self.step_budget:
            trip = BreakerTrip(
                "step_budget",
                f"step budget of {self.step_budget} operations exhausted; "
                "ending the request with no further spend",
            )
            self.trips.append(trip)
            raise trip

    # ------------------------------------------------------------------ state
    @property
    def steps(self) -> int:
        return self._steps

    @property
    def depth(self) -> int:
        return self._depth

    def summary(self) -> dict[str, Any]:
        return {
            "steps": self._steps,
            "depth": self._depth,
            "distinct_states": len(self._state_counts),
            "successful_calls": len(self._successful_calls),
            "trips": [f"{t.kind}: {t.explanation}" for t in self.trips],
        }
