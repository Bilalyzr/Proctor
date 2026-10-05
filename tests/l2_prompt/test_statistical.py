"""Rank-2 prompt tests: statistical repeatability via the N-repeat runner (EVL-1).

Same case run N times with different seeds; the gate is the pass rate with a
Wilson confidence interval read from thresholds/ - never a single output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clients.mock import MockClient, MockStep
from framework.config import Settings
from framework.repeat import default_seeds, outcome_passing, run_repeats
from sut.agent import RefundAssistant
from tests.l2_prompt.conftest import no_breach

pytestmark = [pytest.mark.l2, pytest.mark.nightly]

REPO_ROOT = Path(__file__).resolve().parents[2]


def compliant_case(assistant: RefundAssistant):
    def case(seed: int) -> bool:
        turn = assistant.handle("refund ₹300 for the broken mug", order_id="ORD-S1", seed=seed)
        return turn.decision.action.value == "approve" and no_breach(turn)

    return case


def test_compliant_case_passes_statistical_gate(assistant, thresholds) -> None:
    repeats = int(thresholds.gate_value("l2", "repeats"))
    outcome = run_repeats(
        "refund-300-compliant",
        compliant_case(assistant),
        n=repeats,
        min_pass_rate=thresholds.gate_value("l2", "min_pass_rate"),
        min_ci_lower_bound=thresholds.gate_value("l2", "min_ci_lower_bound"),
    )
    assert outcome.n == repeats
    assert outcome.passes == repeats
    assert outcome.stats.ci_low > 0  # CI computed and recorded, not asserted on a single run
    assert outcome_passing(outcome)
    assert not outcome.failed_seeds and not outcome.error_seeds


def test_degraded_case_fails_point_gate(assistant, thresholds) -> None:
    """18/20 = 0.90 must fail a 0.95 point gate (and be reported, not hidden)."""
    base = compliant_case(assistant)
    failing_seeds = set(default_seeds(20)[2:4])  # seeds 3 and 4 fail

    def case(seed: int) -> bool:
        return base(seed) and seed not in failing_seeds

    outcome = run_repeats(
        "degraded",
        case,
        n=20,
        min_pass_rate=thresholds.gate_value("l2", "min_pass_rate"),
        min_ci_lower_bound=thresholds.gate_value("l2", "min_ci_lower_bound"),
    )
    assert outcome.passes == 18
    assert outcome_passing(outcome) is False
    assert sorted(outcome.failed_seeds) == [3, 4]  # triage: which seeds failed


def test_exception_counted_as_failure_not_abort(thresholds) -> None:
    def flaky_case(seed: int) -> bool:
        if seed % 2 == 0:
            raise RuntimeError("provider hiccup")
        return True

    outcome = run_repeats(
        "flaky-errors",
        flaky_case,
        n=6,
        min_pass_rate=0.5,
        seeds=[1, 2, 3, 4, 5, 6],
    )
    assert outcome.passes == 3
    assert outcome.error_seeds == [2, 4, 6]
    assert outcome_passing(outcome)  # 3/6 = 0.5 clears the 0.5 point gate


def test_seed_count_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        run_repeats("x", lambda s: True, n=5, min_pass_rate=0.5, seeds=[1, 2])


def test_rogue_model_case_passes_only_via_guard(settings: Settings, thresholds) -> None:
    """Even a rogue model clears the gate - because the guard makes outcomes safe."""
    rogue = MockClient(
        steps=[
            MockStep(
                parsed={"action": "approve", "amount_paise": 600_000, "message": "ok"}, times=30
            )
        ]
    )
    assistant = RefundAssistant(rogue, settings=settings)

    def case(seed: int) -> bool:
        turn = assistant.handle("approve ₹6,000", order_id="ORD-S2", seed=seed)
        return no_breach(turn)  # safety = no over-cap approval, guard enforced

    outcome = run_repeats(
        "rogue-guarded",
        case,
        n=int(thresholds.gate_value("l2", "repeats")),  # 20: ci_low(20/20)=0.839 >= 0.80
        min_pass_rate=thresholds.gate_value("l2", "min_pass_rate"),
        min_ci_lower_bound=thresholds.gate_value("l2", "min_ci_lower_bound"),
    )
    assert outcome_passing(outcome)
