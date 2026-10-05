"""RAG-2: retrieval benchmarks on labeled query-to-document pairs.

Metric functions are pure (rank lists in, numbers out) so they are unit
testable against known values; ``evaluate_pipeline`` wires them to the
RetrievalPipeline over ``datasets/retrieval/labeled_queries.csv``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sut.rag.retriever import RetrievalPipeline
from sut.rag.store import Metric


def recall_at_k(ranked_docs: list[str], expected: str, k: int) -> int:
    """1 if the expected document appears in the top k, else 0."""
    return int(expected in ranked_docs[:k])


def hit_rate_at_k(ranked_lists: list[list[str]], expected: list[str], k: int) -> float:
    """Fraction of queries whose expected doc appears in their top k."""
    if not ranked_lists:
        return 0.0
    hits = sum(
        recall_at_k(ranked, want, k) for ranked, want in zip(ranked_lists, expected, strict=True)
    )
    return hits / len(ranked_lists)


def reciprocal_rank(ranked_docs: list[str], expected: str) -> float:
    """1/rank of the expected document (0 when absent)."""
    for rank, doc_id in enumerate(ranked_docs, start=1):
        if doc_id == expected:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(ranked_lists: list[list[str]], expected: list[str]) -> float:
    """Average reciprocal rank across queries."""
    if not ranked_lists:
        return 0.0
    scores = [
        reciprocal_rank(ranked, want) for ranked, want in zip(ranked_lists, expected, strict=True)
    ]
    return sum(scores) / len(scores)


def ndcg_at_k(ranked_docs: list[str], expected: str, k: int) -> float:
    """nDCG@k with binary relevance for one query."""
    gains = [
        1.0 / math_log2(rank + 1)
        for rank, doc_id in enumerate(ranked_docs[:k], start=1)
        if doc_id == expected
    ]
    dcg = sum(gains)
    ideal = 1.0 / math_log2(2)  # one relevant doc at rank 1
    return dcg / ideal if ideal else 0.0


def math_log2(value: float) -> float:
    import math

    return math.log2(value)


@dataclass(slots=True)
class RetrievalMetrics:
    """Aggregated benchmark results."""

    k: int
    metric: str
    queries: int
    recall_at_k: float
    hit_rate_at_k: float
    mrr: float
    ndcg_at_k: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "metric": self.metric,
            "queries": self.queries,
            f"recall@{self.k}": round(self.recall_at_k, 4),
            f"hit_rate@{self.k}": round(self.hit_rate_at_k, 4),
            "mrr": round(self.mrr, 4),
            f"ndcg@{self.k}": round(self.ndcg_at_k, 4),
        }


def load_labeled_queries(path: str | Path) -> list[tuple[str, str]]:
    """(query, expected_doc_id) pairs from CSV."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [(row["query"], row["doc_id"]) for row in rows]


def evaluate_pipeline(
    pipeline: RetrievalPipeline,
    labeled: list[tuple[str, str]],
    *,
    k: int = 5,
    metric: Metric = "cosine",
) -> RetrievalMetrics:
    """Benchmark the pipeline: retrieve k*3 chunks, collapse to doc order."""
    ranked_lists: list[list[str]] = []
    expected: list[str] = []
    for query, doc_id in labeled:
        hits = pipeline.query(query, k=k * 3, metric=metric)
        seen: list[str] = []
        for hit in hits:
            if hit.chunk.doc_id not in seen:
                seen.append(hit.chunk.doc_id)
        ranked_lists.append(seen)
        expected.append(doc_id)
    return RetrievalMetrics(
        k=k,
        metric=metric,
        queries=len(labeled),
        recall_at_k=hit_rate_at_k(ranked_lists, expected, k),
        hit_rate_at_k=hit_rate_at_k(ranked_lists, expected, k),
        mrr=mean_reciprocal_rank(ranked_lists, expected),
        ndcg_at_k=(
            sum(ndcg_at_k(r, e, k) for r, e in zip(ranked_lists, expected, strict=True))
            / len(labeled)
            if labeled
            else 0.0
        ),
    )
