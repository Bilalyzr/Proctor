"""N-repeat runner (EVL-1): every case runs N times, gates use pass rate + CI.

The runner is provider-agnostic: it takes a callable ``case(seed) -> bool`` so
prompt suites, agent tasks and security probes all share one statistical core.
Seeds are explicit and deterministic, which makes a failing seed list part of
the triage output.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from framework.statistics import (
    Z_95,
    GateResult,
    PassRateStats,
    evaluate_rate_gate,
    pass_rate_stats,
)


@dataclass(slots=True)
class RepeatOutcome:
    """Aggregate result of one case run N times."""

    case_id: str
    n: int
    passed_seeds: list[int] = field(default_factory=list)
    failed_seeds: list[int] = field(default_factory=list)
    error_seeds: list[int] = field(default_factory=list)
    gate: GateResult | None = None
    lower_bound_gate: GateResult | None = None

    @property
    def passes(self) -> int:
        return len(self.passed_seeds)

    @property
    def stats(self) -> PassRateStats:
        return pass_rate_stats(self.passes, self.n)


def default_seeds(n: int, base: int = 1) -> list[int]:
    """Deterministic seed sequence for N repeats."""
    if n < 1:
        msg = f"n must be >= 1, got {n}"
        raise ValueError(msg)
    return list(range(base, base + n))


def run_repeats(
    case_id: str,
    case: Callable[[int], bool],
    *,
    n: int,
    min_pass_rate: float,
    min_ci_lower_bound: float | None = None,
    seeds: Iterable[int] | None = None,
    z: float = Z_95,
) -> RepeatOutcome:
    """Run ``case(seed)`` N times and evaluate the statistical gates.

    Exceptions inside ``case`` count as failures (seed recorded in
    ``error_seeds``) rather than aborting the run - a transient provider error
    must not hide the pass rate.
    """
    seed_list = list(seeds) if seeds is not None else default_seeds(n)
    if len(seed_list) != n:
        msg = f"expected {n} seeds, got {len(seed_list)}"
        raise ValueError(msg)
    outcome = RepeatOutcome(case_id=case_id, n=n)
    for seed in seed_list:
        try:
            if case(seed):
                outcome.passed_seeds.append(seed)
            else:
                outcome.failed_seeds.append(seed)
        except Exception:
            outcome.error_seeds.append(seed)
    outcome.gate = evaluate_rate_gate(case_id, outcome.passes, n, min_pass_rate, "point", z)
    if min_ci_lower_bound is not None:
        outcome.lower_bound_gate = evaluate_rate_gate(
            f"{case_id}:ci_lower_bound", outcome.passes, n, min_ci_lower_bound, "lower_bound", z
        )
    return outcome


def outcome_passing(outcome: RepeatOutcome) -> bool:
    """True when the point gate and (if present) the CI-lower-bound gate pass."""
    assert outcome.gate is not None
    if not outcome.gate.passed:
        return False
    ci_gate_ok = outcome.lower_bound_gate is None or outcome.lower_bound_gate.passed
    return ci_gate_ok
