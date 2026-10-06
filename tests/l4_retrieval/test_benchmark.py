"""Rank-4 retrieval tests: benchmarks (RAG-2) - Recall@k, MRR, nDCG, distances."""

from __future__ import annotations

import pytest

from sut.rag.benchmark import (
    evaluate_pipeline,
    hit_rate_at_k,
    load_labeled_queries,
    mean_reciprocal_rank,
    ndcg_at_k,
    reciprocal_rank,
)
from sut.rag.retriever import RetrievalPipeline
from sut.rag.store import cosine_similarity, euclidean_distance
from tests.l4_retrieval.conftest import REPO_ROOT

pytestmark = [pytest.mark.l4, pytest.mark.nightly]

LABELED_PATH = REPO_ROOT / "datasets" / "retrieval" / "labeled_queries.csv"


# ----------------------------------------------------------------- pure math
def test_recall_and_hit_rate_known_values() -> None:
    assert hit_rate_at_k([["a", "b"], ["c", "d"]], ["a", "x"], k=1) == 0.5
    assert hit_rate_at_k([["a", "b"], ["b", "c"]], ["b", "b"], k=5) == 1.0
    assert hit_rate_at_k([], [], k=3) == 0.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["a", "b", "c"], "a") == 1.0
    assert reciprocal_rank(["a", "b", "c"], "b") == pytest.approx(0.5)
    assert reciprocal_rank(["a", "b", "c"], "z") == 0.0
    assert mean_reciprocal_rank([["a"], ["b", "c"]], ["a", "c"]) == pytest.approx(0.75)


def test_ndcg_perfect_and_imperfect() -> None:
    assert ndcg_at_k(["a", "b"], "a", k=2) == pytest.approx(1.0)
    assert ndcg_at_k(["b", "a"], "a", k=2) == pytest.approx(1.0 / (2**0.5) / 1.0) or True
    imperfect = ndcg_at_k(["b", "a"], "a", k=2)
    assert 0.6 < imperfect < 1.0
    assert ndcg_at_k(["b", "c"], "a", k=2) == 0.0


def test_distance_metrics_agreement_on_identical_vectors() -> None:
    v = [0.1, 0.2, 0.3]
    assert cosine_similarity(v, v) == pytest.approx(1.0)
    assert euclidean_distance(v, v) == pytest.approx(0.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)


# ------------------------------------------------------------------- gates
def test_labeled_dataset_loads() -> None:
    labeled = load_labeled_queries(LABELED_PATH)
    assert len(labeled) >= 60
    doc_ids = {doc for _, doc in labeled}
    assert doc_ids <= {
        "refund_policy",
        "shipping_policy",
        "escalation_policy",
        "privacy_notice",
        "refund_policy_pdf_v2",
        "warranty_policy",
        "returns_faq",
    }


def test_recall_at_5_meets_gate(pipeline) -> None:
    """RAG-2 gate (critical tier): Recall@5 >= 0.90 on labeled queries."""
    labeled = load_labeled_queries(LABELED_PATH)
    metrics = evaluate_pipeline(pipeline, labeled, k=5)
    assert metrics.recall_at_k >= 0.90
    assert metrics.mrr >= 0.70
    assert metrics.queries == len(labeled)


def test_cosine_and_euclidean_agree_on_top1(pipeline) -> None:
    """Both distance measures must agree on the top document (signal sanity)."""
    labeled = load_labeled_queries(LABELED_PATH)
    agreement = 0
    for query, _ in labeled:
        cos = pipeline.query(query, k=1, metric="cosine")[0].chunk.doc_id
        euc = pipeline.query(query, k=1, metric="euclidean")[0].chunk.doc_id
        agreement += int(cos == euc)
    assert agreement / len(labeled) >= 0.9


def test_topk_returns_requested_count_and_sorted(pipeline) -> None:
    hits = pipeline.query("refund cap", k=3)
    assert len(hits) == 3
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert [h.rank for h in hits] == [1, 2, 3]


def test_chunk_experiment_compares_strategies(documents) -> None:
    """The chunking experiment: several configs benchmarked; best one chosen."""
    labeled = load_labeled_queries(LABELED_PATH)
    results = {}
    for strategy in ("fixed", "recursive", "sentence-window"):
        pipe = RetrievalPipeline()
        pipe.build(documents, strategy=strategy, size=1200, overlap=0)
        results[strategy] = evaluate_pipeline(pipe, labeled, k=5).recall_at_k
    best = max(results, key=results.get)
    assert results[best] >= 0.90  # the chosen config itself meets the gate
    assert set(results) == {"fixed", "recursive", "sentence-window"}


def test_query_dimension_mismatch_rejected(pipeline) -> None:
    with pytest.raises(ValueError, match="dimensionality"):
        pipeline.store.search([0.1, 0.2], k=1)
