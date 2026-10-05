"""Population Stability Index drift detection (PRD-2, blueprint Domain 2).

PSI per feature/score between a reference and current sample. Reading guide
(framework thresholds, matching the blueprint's metric reference):
PSI < 0.1 stable, 0.1-0.25 investigate, > 0.25 alert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STABLE = 0.1  # PSI below this: stable
INVESTIGATE = 0.25  # PSI in [0.1, 0.25]: investigate; above: alert


def _bucketize(values: list[float], edges: list[float]) -> list[int]:
    counts = [0] * (len(edges) + 1)
    for value in values:
        index = 0
        while index < len(edges) and value > edges[index]:
            index += 1
        counts[index] += 1
    return counts


def _quantile_edges(values: list[float], buckets: int) -> list[float]:
    ordered = sorted(values)
    if not ordered:
        return []
    edges = []
    for i in range(1, buckets):
        position = (len(ordered) - 1) * i / buckets
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - lower
        edges.append(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)
    return sorted(set(edges))


def psi(reference: list[float], current: list[float], *, buckets: int = 5) -> float:
    """Population Stability Index between two samples (0 = identical)."""
    if not reference or not current:
        raise ValueError("both samples must be non-empty")
    edges = _quantile_edges(reference, buckets)
    ref_counts = _bucketize(reference, edges)
    cur_counts = _bucketize(current, edges)
    total_ref, total_cur = sum(ref_counts), sum(cur_counts)
    value = 0.0
    for ref_count, cur_count in zip(ref_counts, cur_counts, strict=True):
        p = max(ref_count / total_ref, 1e-6)
        q = max(cur_count / total_cur, 1e-6)
        value += (q - p) * _log(q / p)
    return value


def _log(x: float) -> float:
    import math

    return math.log(x)


@dataclass(slots=True)
class DriftReport:
    """PSI result with the framework's reading."""

    metric: str
    psi: float
    status: str  # "stable" | "investigate" | "alert"

    def as_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "psi": round(self.psi, 4), "status": self.status}


def psi_report(metric: str, reference: list[float], current: list[float]) -> DriftReport:
    """Compute PSI and classify per the blueprint bands."""
    value = psi(reference, current)
    if value < STABLE:
        status = "stable"
    elif value <= INVESTIGATE:
        status = "investigate"
    else:
        status = "alert"
    return DriftReport(metric=metric, psi=value, status=status)
