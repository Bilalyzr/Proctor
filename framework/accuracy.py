"""The accuracy engine: measure truth precisely, decide with less.

Three capabilities no E2E/AI testing framework in the comparison set has:

1. **Exact intervals** - Clopper-Pearson (exact binomial) alongside Wilson:
   guaranteed coverage, no small-N liberalness.
2. **Sequential testing (SPRT)** - Wald's sequential probability ratio test
   decides "meets gate" vs "below gate" the moment the evidence suffices,
   instead of burning a fixed N. Typical saving: 40-70% of the runs for the
   same error rates - which is exactly how you buy accuracy per dollar.
3. **Measurement-error benchmarking** - inject generators with KNOWN pass
   rates and measure how closely the framework's estimate lands (mean
   absolute error) and whether the confidence interval actually covers the
   truth at its nominal level. "Our framework is accurate" becomes a gated
   number instead of a claim.

CLI: python -m framework.accuracy [--full]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# exact binomial machinery (no scipy; log-space for stability)
# ---------------------------------------------------------------------------


def _log_binom_pmf(k: int, n: int, p: float) -> float:
    return (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log1p(-p)
    )


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binom(n, p), computed exactly in log space."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    p = min(max(p, 1e-12), 1 - 1e-12)
    logs = [_log_binom_pmf(i, n, p) for i in range(k + 1)]
    top = max(logs)
    return min(1.0, math.exp(top) * sum(math.exp(value - top) for value in logs))


def clopper_pearson(passes: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    """Exact binomial confidence interval (guaranteed coverage).

    Lower bound p_L solves CDF(k-1; n, p_L) = 1 - alpha/2; upper bound p_U
    solves CDF(k; n, p_U) = alpha/2. Degenerate counts use the closed forms
    1-(alpha/2)^(1/n) and (alpha/2)^(1/n).
    """
    if total <= 0:
        msg = f"total must be >= 1, got {total}"
        raise ValueError(msg)
    alpha = 1.0 - confidence
    if passes == 0:
        return 0.0, 1.0 - (alpha / 2) ** (1.0 / total)
    if passes == total:
        return (alpha / 2) ** (1.0 / total), 1.0
    low = _invert_cdf(passes - 1, total, 1 - alpha / 2)
    high = _invert_cdf(passes, total, alpha / 2)
    return low, high


def _invert_cdf(k: int, n: int, target: float) -> float:
    """Binary search: find p such that CDF(k; n, p) == target."""
    lo_p, hi_p = 1e-12, 1.0 - 1e-12
    for _ in range(200):
        mid = (lo_p + hi_p) / 2
        if binom_cdf(k, n, mid) > target:
            lo_p = mid  # CDF decreases in p; need higher p to lower CDF
        else:
            hi_p = mid
    return (lo_p + hi_p) / 2


# ---------------------------------------------------------------------------
# sequential testing (SPRT)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SPRTResult:
    decision: str  # "meets" | "below" | "inconclusive"
    threshold: float
    samples_used: int
    passes: int
    point_rate: float
    ci_low: float
    ci_high: float

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "threshold": self.threshold,
            "samples_used": self.samples_used,
            "passes": self.passes,
            "point_rate": round(self.point_rate, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
        }


def sprt(
    case: Callable[[int], bool],
    threshold: float,
    *,
    indifference: float = 0.03,
    alpha: float = 0.05,
    beta: float = 0.10,
    max_samples: int = 500,
) -> SPRTResult:
    """Sequential probability ratio test for a pass-rate gate.

    H0: rate <= threshold - indifference  (below gate)
    H1: rate >= threshold + indifference  (meets gate)
    Stops the moment the log-likelihood ratio crosses either boundary;
    ``max_samples`` bounds spend. ``case(run_index) -> bool`` supplies the
    observations (distinct seeds keep them independent).
    """
    if not 0.0 < threshold < 1.0:
        msg = f"threshold must be in (0, 1), got {threshold}"
        raise ValueError(msg)
    if not 0.0 < indifference < min(threshold, 1.0 - threshold):
        msg = "indifference must fit inside (0, min(threshold, 1-threshold))"
        raise ValueError(msg)
    p0 = threshold - indifference  # below-gate reference rate
    p1 = threshold + indifference  # meets-gate reference rate
    log_upper = math.log((1.0 - beta) / alpha)  # accept H1 (meets)
    log_lower = math.log(beta / (1.0 - alpha))  # accept H0 (below)
    llr = 0.0
    passes = 0
    n = 0
    decision = "inconclusive"
    while n < max_samples:
        n += 1
        if case(n):
            passes += 1
            llr += math.log(p1 / p0)
        else:
            llr += math.log((1.0 - p1) / (1.0 - p0))
        if llr >= log_upper:
            decision = "meets"
            break
        if llr <= log_lower:
            decision = "below"
            break
    low, high = clopper_pearson(passes, n)
    return SPRTResult(
        decision=decision,
        threshold=threshold,
        samples_used=n,
        passes=passes,
        point_rate=passes / n,
        ci_low=low,
        ci_high=high,
    )


# ---------------------------------------------------------------------------
# majority-vote ensembling (variance reduction across seeds)
# ---------------------------------------------------------------------------


def majority_vote(run_once: Callable[[int], bool], seeds: Sequence[int]) -> tuple[bool, float]:
    """Run the check once per seed; the verdict is the majority.

    Reduces variance-induced wrong verdicts for near-deterministic systems:
    a single flaky seed cannot flip the ensemble. Returns (verdict, share).
    """
    if not seeds:
        msg = "seeds must be non-empty"
        raise ValueError(msg)
    votes = [run_once(seed) for seed in seeds]
    agreement = sum(votes) / len(votes)
    return agreement >= 0.5, agreement


# ---------------------------------------------------------------------------
# measurement-error benchmark (the meta-accuracy gate)
# ---------------------------------------------------------------------------


def bernoulli_generator(true_rate: float, seed: int) -> Callable[[int], bool]:
    """Deterministic generator with a KNOWN pass rate (ground truth)."""
    rng = random.Random(seed)

    def case(_run: int) -> bool:
        return rng.random() < true_rate

    return case


@dataclass(slots=True)
class AccuracySection:
    name: str
    passed: bool
    metrics: dict[str, object] = field(default_factory=dict)
    required: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "metrics": self.metrics,
            "required": self.required,
        }


def benchmark_measurement_accuracy(
    *,
    n: int = 500,
    replications: int = 200,
    true_rates: Sequence[float] = (0.80, 0.90, 0.95, 0.99),
    max_mean_abs_error: float = 0.02,
    min_ci_coverage: float = 0.90,
    sprt_budget_ratio: float = 0.70,
) -> AccuracySection:
    """Inject known rates; measure estimation error, CI coverage and SPRT."""
    import statistics

    errors: list[float] = []
    for rate in true_rates:
        for replication in range(max(1, replications // len(true_rates))):
            gen = bernoulli_generator(rate, seed=1000 * int(rate * 100) + replication)
            passes = sum(1 for run in range(1, n + 1) if gen(run))
            estimate = passes / n
            errors.append(abs(estimate - rate))
    mean_abs_error = statistics.fmean(errors)

    # CI coverage at the nominal 95%: fraction of replications whose exact
    # interval contains the injected true rate
    covered = 0
    coverage_reps = 60
    for replication in range(coverage_reps):
        gen = bernoulli_generator(0.90, seed=77_000 + replication)
        passes = sum(1 for run in range(1, n + 1) if gen(run))
        low, high = clopper_pearson(passes, n, 0.95)
        if low <= 0.90 <= high:
            covered += 1
    coverage = covered / coverage_reps

    # SPRT: clear rates must be decided correctly, and cheaper than fixed-N
    samples_used: list[int] = []
    correct = 0
    clear_cases = [(0.97, "meets"), (0.75, "below"), (0.99, "meets"), (0.60, "below")]
    for rate, expected in clear_cases:
        gen = bernoulli_generator(rate, seed=55_000 + int(rate * 100))
        result = sprt(gen, threshold=0.90, max_samples=n)
        samples_used.append(result.samples_used)
        if result.decision == expected:
            correct += 1
    avg_samples = statistics.fmean(samples_used)
    budget_ratio = avg_samples / n

    passed = (
        mean_abs_error <= max_mean_abs_error
        and coverage >= min_ci_coverage
        and correct == len(clear_cases)
        and budget_ratio <= sprt_budget_ratio
    )
    return AccuracySection(
        name="measurement_accuracy",
        passed=passed,
        metrics={
            "fixed_n": n,
            "true_rates": list(true_rates),
            "mean_abs_estimation_error": round(mean_abs_error, 5),
            "ci_coverage_of_95pct_interval": round(coverage, 4),
            "sprt_decisions_correct": f"{correct}/{len(clear_cases)}",
            "sprt_avg_samples": round(avg_samples, 1),
            "sprt_budget_ratio": round(budget_ratio, 3),
        },
        required={
            "max_mean_abs_error": max_mean_abs_error,
            "min_ci_coverage": min_ci_coverage,
            "sprt_all_correct": True,
            "max_sprt_budget_ratio": sprt_budget_ratio,
        },
    )


def run_benchmark(*, full: bool = False) -> dict[str, object]:
    if full:
        section = benchmark_measurement_accuracy()
    else:
        section = benchmark_measurement_accuracy(n=200, replications=60)
    return {
        "profile": "full" if full else "reduced",
        "passed": section.passed,
        "sections": [section.as_dict()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Accuracy engine benchmark")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    section = (
        benchmark_measurement_accuracy()
        if args.full
        else benchmark_measurement_accuracy(n=200, replications=60)
    )
    status = "PASS" if section.passed else "FAIL"
    print(f"[accuracy] measurement_accuracy {status} {json.dumps(section.as_dict()['metrics'])}")
    if not section.passed:
        print(f"[accuracy] required: {json.dumps(section.as_dict()['required'])}")
    return 0 if section.passed else 1


if __name__ == "__main__":
    sys.exit(main())
