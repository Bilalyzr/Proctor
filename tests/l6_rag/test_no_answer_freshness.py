"""Rank-6 RAG quality: no-answer handling and index freshness (Domain 4)."""

from __future__ import annotations

import pytest

from sut.rag.chunking import chunk_documents
from sut.rag.loader import SourceDocument
from sut.rag.retriever import RetrievalPipeline

pytestmark = [pytest.mark.l6, pytest.mark.nightly]

OUT_OF_CORPUS = [
    "what is the capital of France",
    "who won the cricket world cup",
    "what is ShopFast's stock price",
    "write me a poem about the ocean",
]


@pytest.mark.parametrize("question", OUT_OF_CORPUS)
def test_out_of_corpus_questions_get_no_answer(pipeline, question: str) -> None:
    turn = pipeline.answer(question)
    assert turn.answered is False
    assert "don't know" in turn.answer.lower()


def test_answered_questions_cite_a_source(pipeline) -> None:
    turn = pipeline.answer("how long do refunds take to arrive")
    assert turn.answered is True
    assert turn.sources
    assert turn.contexts  # evidence always attached (citation groundwork)


def test_index_freshness_after_policy_update(documents) -> None:
    """Freshness: update a policy, rebuild, the old text must not be retrieved."""
    updated = []
    for document in documents:
        if document.doc_id == "shipping_policy":
            updated.append(
                SourceDocument(
                    **document.model_dump(exclude={"text"})
                    | {
                        "text": document.text.replace(
                            "Rs 100 shipping credit", "Rs 150 shipping credit"
                        ).replace("14 days", "10 days")
                    }
                )
            )
        else:
            updated.append(document)
    stale = RetrievalPipeline()
    stale.build(documents, strategy="recursive", size=1200, overlap=0)
    fresh = RetrievalPipeline()
    fresh.build(updated, strategy="recursive", size=1200, overlap=0)

    answer_stale = stale.answer("what compensation do i get for late delivery")
    answer_fresh = fresh.answer("what compensation do i get for late delivery")
    assert "Rs 100" in answer_stale.answer
    assert "Rs 150" in answer_fresh.answer
    assert "Rs 100" not in answer_fresh.answer  # the old value is gone

    lost_stale = stale.answer("when is a parcel declared lost")
    lost_fresh = fresh.answer("when is a parcel declared lost")
    assert "14 days" in lost_stale.answer and "10 days" in lost_fresh.answer


def test_chunk_id_stability_across_rebuild(documents) -> None:
    """Chunk ids are deterministic - index diffs are meaningful (freshness)."""
    a = [c.chunk_id for c in chunk_documents(documents, "recursive", size=1200)]
    b = [c.chunk_id for c in chunk_documents(documents, "recursive", size=1200)]
    assert a == b
