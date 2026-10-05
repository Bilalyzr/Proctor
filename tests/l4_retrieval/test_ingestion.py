"""Rank-4 retrieval tests: ingestion verification (RAG-1)."""

from __future__ import annotations

import math

import pytest

from sut.rag.embedder import HashingEmbedder
from sut.rag.verify_ingestion import verify_ingestion, write_report
from tests.l4_retrieval.conftest import POLICIES

pytestmark = [pytest.mark.l4, pytest.mark.nightly]


def test_every_document_parsed_with_counts(documents) -> None:
    by_id = {d.doc_id: d for d in documents}
    assert set(by_id) >= {
        "refund_policy",
        "shipping_policy",
        "escalation_policy",
        "privacy_notice",
        "refund_policy_pdf_v2",
    }
    for document in documents:
        assert document.word_count > 10, f"{document.doc_id} suspiciously short"
    # markdown docs report headings
    assert by_id["refund_policy"].headings_count >= 3
    # the PDF parsed for real, not as an empty shell
    assert by_id["refund_policy_pdf_v2"].format == "pdf"
    assert "Rs 500 per order" in by_id["refund_policy_pdf_v2"].text


def test_pdf_pages_counted(documents) -> None:
    pdf = next(d for d in documents if d.format == "pdf")
    assert pdf.pages >= 1


def test_embedder_produced_normalized_vectors(documents) -> None:
    embedder = HashingEmbedder()
    for document in documents:
        vector = embedder.embed(document.text)
        assert len(vector) == embedder.dim
        norm = math.sqrt(sum(c * c for c in vector))
        assert 0.99 < norm <= 1.01
    empty = embedder.embed("")
    assert all(c == 0.0 for c in empty)


def test_ingestion_verification_gate_100_percent() -> None:
    """RAG-1 gate: every source document is parsed, chunked, embedded, retrievable."""
    report = verify_ingestion(POLICIES, size=1200)
    assert report["documents_total"] == 5
    assert report["indexed_fraction"] == 1.0
    for entry in report["documents"]:
        assert entry["ok"], f"{entry['doc_id']} failed ingestion: {entry}"
        assert entry["chunks"] > 0


def test_unsupported_extensions_are_accounted_not_dropped(tmp_path) -> None:
    (tmp_path / "a.md").write_text("# Doc\n\nSome policy text here.", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG fake")
    report = verify_ingestion(tmp_path)
    assert report["documents_total"] == 1
    assert any("image.png" in entry for entry in report["skipped_sources"])


def test_report_written_to_disk(tmp_path) -> None:
    report = verify_ingestion(POLICIES, size=1200)
    path = write_report(report, tmp_path / "ingestion.json")
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["indexed_fraction"] == 1.0
