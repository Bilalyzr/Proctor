"""Near-duplicate detection for synthetic cases (AST-3).

Word-shingle Jaccard with minhash-style banding: candidate buckets keyed by
the four smallest shingle hashes keep the O(n^2) comparisons inside buckets,
so 100k-case runs stay tractable (datasketch would drop in behind the same
signature functions).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from synthetic.generator import GeneratedCase


def normalize_text(text: str) -> str:
    """Case-fold, drop digits and punctuation noise, collapse whitespace."""
    import re

    lowered = re.sub(r"\d+", " <num> ", text.lower())
    lowered = re.sub(r"[^a-z<> ]+", " ", lowered)
    return " ".join(lowered.split())


def shingles(text: str, width: int = 3) -> set[int]:
    """Hashed word n-gram signature of a text."""
    words = normalize_text(text).split()
    return {
        int.from_bytes(
            hashlib.blake2b(" ".join(words[i : i + width]).encode(), digest_size=8).digest(), "big"
        )
        for i in range(max(1, len(words) - width + 1))
    }


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _band_key(signature: set[int]) -> tuple[int, int, int, int]:
    return tuple(sorted(signature)[:4])  # type: ignore[return-value]


@dataclass(slots=True)
class DedupReport:
    """Outcome of deduplication."""

    kept: list[str] = field(default_factory=list)
    duplicates: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.kept) + len(self.duplicates)

    @property
    def duplicate_rate(self) -> float:
        return (len(self.duplicates) / self.total) if self.total else 0.0


def dedup_cases(
    cases: list[GeneratedCase], *, threshold: float = 0.9, exact_amounts_differ: bool = True
) -> DedupReport:
    """Keep the first of each near-duplicate cluster.

    ``exact_amounts_differ`` treats cases with different paise amounts as
    distinct even when the normalized text matches (numbers are masked).
    """
    report = DedupReport()
    by_id = {case.case_id: case for case in cases}
    signatures: dict[str, set[int]] = {}
    buckets: dict[tuple[int, int, int, int], list[str]] = {}
    for case in cases:
        signature = shingles(case.text)
        signatures[case.case_id] = signature
        bucket = _band_key(signature)
        duplicate_of: str | None = None
        best_similarity = 0.0
        for candidate_id in buckets.get(bucket, []):
            if exact_amounts_differ:
                other = by_id[candidate_id]
                if (case.amount_paise or 0) != (other.amount_paise or 0):
                    continue
            similarity = jaccard(signature, signatures[candidate_id])
            if similarity >= threshold and similarity > best_similarity:
                duplicate_of = candidate_id
                best_similarity = similarity
        if duplicate_of is None:
            report.kept.append(case.case_id)
            buckets.setdefault(bucket, []).append(case.case_id)
        else:
            report.duplicates.append((case.case_id, duplicate_of, round(best_similarity, 4)))
    return report


def apply_dedup(cases: list[GeneratedCase], report: DedupReport) -> list[GeneratedCase]:
    """Filter a case list down to the kept ids in the report."""
    keep = set(report.kept)
    return [case for case in cases if case.case_id in keep]
