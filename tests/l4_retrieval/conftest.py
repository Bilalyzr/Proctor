"""Shared fixtures for retrieval and RAG-quality suites."""

from __future__ import annotations

from pathlib import Path

import pytest

from sut.rag.loader import load_documents
from sut.rag.retriever import RetrievalPipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICIES = REPO_ROOT / "sut" / "data" / "policies"

DEFAULT_STRATEGY = "recursive"
DEFAULT_SIZE = 1200


@pytest.fixture(scope="module")
def documents():
    docs, skipped = load_documents(POLICIES)
    assert not skipped, f"unexpected skipped sources: {skipped}"
    return docs


@pytest.fixture(scope="module")
def pipeline(documents) -> RetrievalPipeline:
    pipe = RetrievalPipeline()
    pipe.build(documents, strategy=DEFAULT_STRATEGY, size=DEFAULT_SIZE, overlap=0)
    return pipe
