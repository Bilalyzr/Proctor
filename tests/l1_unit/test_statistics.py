"""Rank-1 unit tests: statistical primitives (EVL-1 math, used by every gate)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from framework.statistics import (
    Z_95,
    evaluate_max_gate,
    evaluate_rate_gate,
    pass_rate_stats,
    wilson_interval,
)

pytestmark = pytest.mark.l1

# Reference values computed independently from the Wilson score formula
# (25/25 -> [0.867, 1.000] matches the textbook example, validating the math).
REFERENCE = {
    (20, 20): (0.838875, 1.000000),
    (19, 20): (0.763869, 0.991119),
    (25, 25): (0.866808, 1.000000),
    (0, 20): (0.000000, 0.161125),
    (95, 100): (0.888250, 0.978456),
    (5, 5): (0.565518, 1.000000),
    (1, 5): (0.036224, 0.624465),
}


@pytest.mark.parametrize(("k", "n", "expected"), [*[(k, n, v) for (k, n), v in REFERENCE.items()]])
def test_wilson_reference_values(k: int, n: int, expected: tuple[float, float]) -> None:
    low, high = wilson_interval(k, n)
    assert low == pytest.approx(expected[0], abs=1e-5)
    assert high == pytest.approx(expected[1], abs=1e-5)


@pytest.mark.parametrize(
    ("passes", "total"),
    [(0, 0), (-1, 10), (11, 10), (5, -3)],
)
def test_wilson_rejects_invalid_input(passes: int, total: int) -> None:
    with pytest.raises(ValueError):
        wilson_interval(passes, total)


def test_wilson_rejects_bad_z() -> None:
    with pytest.raises(ValueError):
        wilson_interval(1, 10, z=0.0)


@given(
    k=st.integers(min_value=0, max_value=200),
    n=st.integers(min_value=1, max_value=200),
)
def test_wilson_bounds_contain_point_estimate(k: int, n: int) -> None:
    k = min(k, n)
    low, high = wilson_interval(k, n)
    rate = k / n
    assert 0.0 <= low <= rate <= high <= 1.0


@given(n=st.integers(min_value=1, max_value=500))
def test_wilson_interval_shrinks_with_n(n: int) -> None:
    wide = wilson_interval(1, n)
    tight = wilson_interval(1, n * 10 + 9)
    assert (tight[1] - tight[0]) <= (wide[1] - wide[0]) + 1e-12


def test_pass_rate_stats_fields() -> None:
    stats = pass_rate_stats(19, 20)
    assert stats.passes == 19
    assert stats.total == 20
    assert stats.rate == pytest.approx(0.95)
    assert stats.z == Z_95
    assert stats.as_dict()["ci_low"] == stats.ci_low


def test_rate_gate_lower_bound_is_conservative() -> None:
    # 19/20 has point rate 0.95 but its CI lower bound is 0.764: a 0.95 gate
    # in lower_bound mode must FAIL - one lucky sample cannot sign off a release.
    strict = evaluate_rate_gate("prompt-suite", 19, 20, 0.95, mode="lower_bound")
    assert strict.passed is False
    assert strict.observed == pytest.approx(0.763869, abs=1e-5)
    lenient = evaluate_rate_gate("prompt-suite", 19, 20, 0.95, mode="point")
    assert lenient.passed is True
    assert lenient.observed == pytest.approx(0.95)


def test_rate_gate_passes_when_lower_bound_meets_threshold() -> None:
    result = evaluate_rate_gate("unit", 100, 100, 0.85)
    assert result.passed is True
    assert result.stats is not None and result.stats.ci_low >= 0.85


def test_rate_gate_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError):
        evaluate_rate_gate("x", 1, 10, 1.5)


def test_max_gate() -> None:
    ok = evaluate_max_gate("breaches", 0, 0)
    assert ok.passed is True
    bad = evaluate_max_gate("breaches", 1, 0)
    assert bad.passed is False
    assert bad.as_dict()["threshold"] == 0
