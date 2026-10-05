"""Shared golden RAG fixtures (question, ground truth) for L6."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.ragas_metrics import LocalRagasBackend, evaluate_corpus
from sut.rag.loader import load_documents
from sut.rag.retriever import RetrievalPipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICIES = REPO_ROOT / "sut" / "data" / "policies"
BASELINE_PATH = REPO_ROOT / "datasets" / "rag" / "baseline.json"

GOLDEN_QA = [
    (
        "what is the maximum refund amount",
        "The automatic refund cap is Rs 500 per order. "
        "Refunds must never exceed Rs 500 without human approval.",
    ),
    (
        "how long do refunds take to arrive",
        "Refunds are issued to the original payment method within 3 to 5 "
        "business days after approval.",
    ),
    (
        "my parcel is lost what now",
        "A parcel is declared lost after 14 days without a tracking scan. "
        "Lost parcels are reshipped free of charge.",
    ),
    (
        "what compensation do i get for late delivery",
        "Customers receive a Rs 100 shipping credit automatically for late standard delivery.",
    ),
    (
        "when should an agent escalate to a human",
        "Escalate any refund above the Rs 500 cap, legal threats, or a third "
        "occurrence of the same problem.",
    ),
    ("how long are chat transcripts kept", "Chat transcripts are retained for 90 days."),
    (
        "do you store my card number",
        "Card numbers are never stored. Payments are tokenized by the payment processor.",
    ),
]


@pytest.fixture(scope="module")
def documents():
    docs, skipped = load_documents(POLICIES)
    assert not skipped
    return docs


@pytest.fixture(scope="module")
def pipeline(documents) -> RetrievalPipeline:
    pipe = RetrievalPipeline()
    pipe.build(documents, strategy="recursive", size=1200, overlap=0)
    return pipe


@pytest.fixture(scope="module")
def rag_turns(pipeline: RetrievalPipeline):
    return [pipeline.answer(question) for question, _ in GOLDEN_QA]


@pytest.fixture(scope="module")
def ground_truths():
    return [truth for _, truth in GOLDEN_QA]


@pytest.fixture(scope="module")
def corpus_report(rag_turns, ground_truths):
    flags = [[True, True, False, False]] * len(GOLDEN_QA)
    return evaluate_corpus(
        LocalRagasBackend(), rag_turns, ground_truths=ground_truths, relevance_flags=flags
    )
