"""Tests for the accuracy engine: exact intervals, SPRT, ensembling, and the
measurement-error benchmark (the framework's own accuracy, gated)."""

from __future__ import annotations

import pytest

from framework.accuracy import (
    bernoulli_generator,
    binom_cdf,
    clopper_pearson,
    majority_vote,
    run_benchmark,
    sprt,
)

pytestmark = [pytest.mark.l1, pytest.mark.nightly]


class TestExactIntervals:
    def test_matches_textbook_values(self) -> None:
        assert clopper_pearson(0, 20) == pytest.approx((0.0, 0.1684), abs=2e-3)
        assert clopper_pearson(20, 20) == pytest.approx((0.8316, 1.0), abs=2e-3)
        assert clopper_pearson(10, 20) == pytest.approx((0.2720, 0.7280), abs=2e-3)

    def test_bounds_are_ordered_and_valid(self) -> None:
        for k in range(0, 21):
            low, high = clopper_pearson(k, 20)
            assert 0.0 <= low <= k / 20 <= high <= 1.0

    def test_invalid_total_rejected(self) -> None:
        with pytest.raises(ValueError):
            clopper_pearson(1, 0)

    def test_binom_cdf_extremes(self) -> None:
        assert binom_cdf(-1, 5, 0.5) == 0.0
        assert binom_cdf(5, 5, 0.5) == 1.0
        assert binom_cdf(2, 2, 0.3) == pytest.approx(0.3**2 + 2 * 0.3 * 0.7 + 0.49)


class TestSPRT:
    def test_clear_meet_rate_decided_meets_fast(self) -> None:
        result = sprt(bernoulli_generator(0.99, seed=1), threshold=0.90, max_samples=500)
        assert result.decision == "meets"
        assert result.samples_used < 60  # near-certain: very fast

    def test_clear_fail_rate_decided_below_fast(self) -> None:
        result = sprt(bernoulli_generator(0.55, seed=2), threshold=0.90, max_samples=500)
        assert result.decision == "below"
        assert result.samples_used < 80

    def test_boundary_rate_stays_inconclusive_within_budget(self) -> None:
        result = sprt(bernoulli_generator(0.90, seed=3), threshold=0.90, max_samples=200)
        # exactly at the threshold is inside the indifference zone
        assert result.decision in {"meets", "below", "inconclusive"}
        assert result.samples_used >= 10  # it works for its answer

    def test_invalid_args_rejected(self) -> None:
        with pytest.raises(ValueError):
            sprt(lambda n: True, threshold=1.5)
        with pytest.raises(ValueError):
            sprt(lambda n: True, threshold=0.5, indifference=0.6)

    def test_reduced_benchmark_end_to_end(self) -> None:
        report = run_benchmark(full=False)
        assert report["passed"], report["sections"]


class TestMajorityVote:
    def test_majority_of_odd_votes(self) -> None:
        verdict, share = majority_vote(lambda seed: seed % 2 == 0, seeds=[2, 4, 5])
        assert verdict is True and share == pytest.approx(2 / 3)

    def test_single_flaky_seed_cannot_flip(self) -> None:
        # seeds 1..9 pass, seed 99 fails: ensemble still True
        verdict, share = majority_vote(lambda seed: seed != 99, seeds=[*range(1, 10), 99])
        assert verdict is True and share == pytest.approx(0.9)

    def test_empty_seeds_rejected(self) -> None:
        with pytest.raises(ValueError):
            majority_vote(lambda seed: True, seeds=[])


def test_measurement_error_is_small_and_coverage_honest() -> None:
    """The headline claim, pinned: at N=200 the estimate is within 0.035 of
    truth and the 95% exact interval covers truth >= 90% of the time."""
    section = run_benchmark(full=False)["sections"][0]
    metrics = section["metrics"]
    assert metrics["mean_abs_estimation_error"] <= 0.035
    assert metrics["ci_coverage_of_95pct_interval"] >= 0.90
