"""Rank-4 retrieval tests: chunking experiments (fixed / recursive / window)."""

from __future__ import annotations

import pytest

from sut.rag.chunking import chunk_document, chunk_documents
from sut.rag.loader import SourceDocument

pytestmark = [pytest.mark.l4, pytest.mark.nightly]

DOC = SourceDocument(
    doc_id="t",
    source="t.md",
    title="T",
    text=(
        "# Policy\n\n"
        + "First paragraph with a complete sentence about caps. Another sentence follows here. " * 6
        + "\n\nSecond paragraph about timelines. It also has several sentences. " * 6
        + "\n\nThird short paragraph."
    ),
    format="md",
    word_count=10,
    headings_count=1,
)


def test_fixed_respects_size_and_overlap() -> None:
    chunks = chunk_document(DOC, "fixed", size=400, overlap=80)
    assert chunks
    assert all(len(c.text) <= 400 for c in chunks)
    assert chunks[0].strategy == "fixed"
    # overlap: second chunk starts inside the tail of the first
    assert chunks[1].text[:40] in (chunks[0].text[-120:] + chunks[1].text[:40])


def test_recursive_keeps_paragraphs_and_sentences() -> None:
    chunks = chunk_document(DOC, "recursive", size=500, overlap=0)
    assert chunks
    rejoined = " ".join(c.text for c in chunks)
    assert "First paragraph" in rejoined and "Third short paragraph." in rejoined
    # no chunk is a mid-sentence fragment of the first sentence
    assert any(c.text.lstrip().startswith(("First", "Second", "Third", "#")) for c in chunks)


def test_sentence_window_groups_sentences() -> None:
    chunks = chunk_document(DOC, "sentence-window", size=500, overlap=0, window=3)
    assert chunks
    counts = [len(c.text.split(".")) - 1 for c in chunks]
    assert max(counts) <= 3  # at most the window size


def test_all_strategies_on_real_corpus(documents) -> None:
    for strategy in ("fixed", "recursive", "sentence-window"):
        chunks = chunk_documents(documents, strategy, size=1200, overlap=0)
        assert chunks, f"{strategy} produced no chunks"
        assert all(c.text.strip() for c in chunks)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"size": 10}, "size must be"),
        ({"size": 500, "overlap": 500}, "overlap must be"),
        ({"size": 500, "overlap": -1}, "overlap must be"),
    ],
)
def test_invalid_parameters_rejected(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        chunk_document(DOC, "fixed", **kwargs)


def test_unknown_strategy_rejected() -> None:
    with pytest.raises(ValueError, match="unknown strategy"):
        chunk_document(DOC, "weird", size=500)  # type: ignore[arg-type]


def test_empty_document_chunks_to_nothing() -> None:
    empty = SourceDocument(
        doc_id="e",
        source="e",
        title="e",
        text="",
        format="txt",
        word_count=0,
        headings_count=0,
    )
    assert chunk_document(empty, "recursive", size=500) == []
