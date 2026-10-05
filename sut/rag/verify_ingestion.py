"""RAG-1: ingestion verification report.

Every source document must be verified as parsed, chunked, embedded and
retrievable - the blueprint's gate is 100% of source documents indexed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sut.rag.chunking import Strategy
from sut.rag.loader import load_documents
from sut.rag.retriever import RetrievalPipeline, content_words


def verify_ingestion(
    root: str | Path,
    *,
    strategy: Strategy = "recursive",
    size: int = 2048,
    overlap: int = 0,
    k: int = 3,
) -> dict[str, Any]:
    """Full ingestion verification report (JSON-serializable)."""
    documents, skipped = load_documents(root)
    pipeline = RetrievalPipeline()
    pipeline.build(documents, strategy=strategy, size=size, overlap=overlap)

    per_doc: list[dict[str, Any]] = []
    for document in documents:
        chunks = [c for c in pipeline.chunks.values() if c.doc_id == document.doc_id]
        embedded_ok = bool(chunks) and len(pipeline.store) >= len(pipeline.chunks)
        keywords = " ".join(sorted(content_words(document.text))[:8])
        probe = f"{document.title} {keywords}"
        ranked_docs = [hit.chunk.doc_id for hit in pipeline.query(probe, k=max(k, 3))]
        retrievable = document.doc_id in ranked_docs
        parsed_ok = document.word_count > 0
        entry = {
            "doc_id": document.doc_id,
            "format": document.format,
            "parsed": parsed_ok,
            "word_count": document.word_count,
            "headings_count": document.headings_count,
            "pages": document.pages,
            "chunks": len(chunks),
            "chunked": len(chunks) > 0,
            "embedded": embedded_ok,
            "retrievable": retrievable,
        }
        entry["ok"] = all(entry[key] for key in ("parsed", "chunked", "embedded", "retrievable"))
        per_doc.append(entry)

    total = len(per_doc)
    passed = sum(1 for entry in per_doc if entry["ok"])
    return {
        "root": str(root),
        "documents_total": total,
        "documents_ok": passed,
        "indexed_fraction": (passed / total) if total else 0.0,
        "gate": "indexed_fraction == 1.0",
        "skipped_sources": skipped,
        "documents": per_doc,
        "index_stats": pipeline.config,
    }


def write_report(report: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return target
