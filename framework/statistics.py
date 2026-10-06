"""Statistical primitives for probabilistic gates (blueprint SS1.2 / EVL-1).

Non-deterministic checks run N times and gates assert on the pass rate with a
confidence interval, never on a single output. The Wilson score interval is used
because it behaves correctly at the extremes (0/n and n/n), where the naive
normal-approximation interval degenerates.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Z_95 = 1.959963984540054  # two-sided 95% normal quantile

GateMode = Literal["lower_bound", "point"]


@dataclass(frozen=True)
class PassRateStats:
    """Pass-rate point estimate plus Wilson confidence interval."""

    passes: int
    total: int
    rate: float
    ci_low: float
    ci_high: float
    z: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "passes": self.passes,
            "total": self.total,
            "rate": self.rate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "z": self.z,
        }


def wilson_interval(passes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Raises ValueError for invalid inputs (n=0, negative counts, passes>total).
    """
    if total <= 0:
        msg = f"total must be >= 1, got {total}"
        raise ValueError(msg)
    if passes < 0 or passes > total:
        msg = f"passes must be in [0, total], got {passes}/{total}"
        raise ValueError(msg)
    if z <= 0:
        msg = f"z must be positive, got {z}"
        raise ValueError(msg)

    n = total
    p_hat = passes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    spread = z * ((p_hat * (1.0 - p_hat) / n) + z2 / (4.0 * n * n)) ** 0.5 / denom
    low = max(0.0, center - spread)
    high = min(1.0, center + spread)
    # snap float dust onto the exact bounds (k=n mathematically reaches 1.0)
    epsilon = 1e-12
    if low < epsilon:
        low = 0.0
    if high > 1.0 - epsilon:
        high = 1.0
    return low, high


def pass_rate_stats(passes: int, total: int, z: float = Z_95) -> PassRateStats:
    """Point estimate and Wilson CI for a pass count."""
    low, high = wilson_interval(passes, total, z)
    return PassRateStats(
        passes=passes,
        total=total,
        rate=passes / total,
        ci_low=low,
        ci_high=high,
        z=z,
    )


@dataclass(frozen=True)
class GateResult:
    """Outcome of one statistical gate evaluation."""

    name: str
    passed: bool
    threshold: float
    mode: GateMode
    observed: float  # the statistic actually compared (lower bound or point)
    stats: PassRateStats | None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "threshold": self.threshold,
            "mode": self.mode,
            "observed": self.observed,
            "stats": self.stats.as_dict() if self.stats is not None else None,
        }


def evaluate_rate_gate(
    name: str,
    passes: int,
    total: int,
    min_pass_rate: float,
    mode: GateMode = "lower_bound",
    z: float = Z_95,
) -> GateResult:
    """Evaluate a pass-rate gate.

    ``lower_bound`` (default, conservative): the Wilson CI *lower* bound must
    meet the threshold, so 19/20 does not clear a 0.95 gate - exactly the
    blueprint's intent that a single lucky sample never signs off a release.
    ``point``: the raw pass rate must meet the threshold.
    """
    if not 0.0 <= min_pass_rate <= 1.0:
        msg = f"min_pass_rate must be in [0, 1], got {min_pass_rate}"
        raise ValueError(msg)
    stats = pass_rate_stats(passes, total, z)
    observed = stats.ci_low if mode == "lower_bound" else stats.rate
    return GateResult(
        name=name,
        passed=observed >= min_pass_rate,
        threshold=min_pass_rate,
        mode=mode,
        observed=observed,
        stats=stats,
    )


def evaluate_max_gate(name: str, observed: float, maximum: float) -> GateResult:
    """Evaluate an upper-bound gate (e.g. zero policy breaches, max latency)."""
    return GateResult(
        name=name,
        passed=observed <= maximum,
        threshold=maximum,
        mode="point",
        observed=observed,
        stats=None,
    )


# ---------------------------------------------------------------------- ranks


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Ranks (1-based) with ties replaced by their average."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j + 2) / 2.0  # ranks are 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def spearman_rho(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman rank correlation (tie-aware, Pearson over average ranks)."""
    if len(x) != len(y):
        msg = f"length mismatch: {len(x)} vs {len(y)}"
        raise ValueError(msg)
    if len(x) < 2:
        msg = "need at least two pairs"
        raise ValueError(msg)
    rank_x = _average_ranks(list(x))
    rank_y = _average_ranks(list(y))
    mean_x = sum(rank_x) / len(rank_x)
    mean_y = sum(rank_y) / len(rank_y)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(rank_x, rank_y, strict=True))
    denom_x = sum((a - mean_x) ** 2 for a in rank_x) ** 0.5
    denom_y = sum((b - mean_y) ** 2 for b in rank_y) ** 0.5
    if denom_x == 0.0 or denom_y == 0.0:
        return 0.0  # constant input carries no rank information
    return numerator / (denom_x * denom_y)


# ------------------------------------------------------------ classifier metrics


def confusion_matrix(
    predicted: Sequence[object], actual: Sequence[object]
) -> dict[tuple[object, object], int]:
    """Pairwise counts keyed by (predicted, actual) - label-agnostic."""
    if len(predicted) != len(actual):
        msg = f"length mismatch: {len(predicted)} vs {len(actual)}"
        raise ValueError(msg)
    counts: dict[tuple[object, object], int] = {}
    for pred, truth in zip(predicted, actual, strict=True):
        counts[(pred, truth)] = counts.get((pred, truth), 0) + 1
    return counts


def precision_recall_f1(predicted: Sequence[bool], actual: Sequence[bool]) -> dict[str, float]:
    """Binary precision/recall/F1 (positive class = True)."""
    matrix = confusion_matrix(predicted, actual)
    tp = matrix.get((True, True), 0)
    fp = matrix.get((True, False), 0)
    fn = matrix.get((False, True), 0)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def slice_parity(
    slices: dict[str, Sequence[bool]],
    *,
    max_gap: float = 0.05,
) -> dict[str, object]:
    """Blueprint Domain-2 gate: no slice more than ``max_gap`` below overall."""
    overall = [value for values in slices.values() for value in values]
    overall_rate = sum(overall) / len(overall) if overall else 0.0
    per_slice = {
        name: (sum(values) / len(values) if values else 0.0) for name, values in slices.items()
    }
    failing = {
        name: round(overall_rate - rate, 4)
        for name, rate in per_slice.items()
        if overall_rate - rate > max_gap
    }
    return {
        "overall_rate": round(overall_rate, 4),
        "per_slice": {name: round(rate, 4) for name, rate in per_slice.items()},
        "max_gap": max_gap,
        "failing_slices": failing,
        "passed": not failing,
    }
