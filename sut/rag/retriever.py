"""Retrieval pipeline: index documents, query with top-k, extractive answers.

The answer generator is deliberately *extractive and context-grounded*: it
answers only from retrieved text, and says "I don't know" when nothing in the
context overlaps the question (no-answer handling, blueprint Domain 4). That
keeps Faithfulness high by construction and makes the Phase 6 guardrails'
DLP-on-context job tractable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sut.rag.chunking import Chunk, Strategy, chunk_documents
from sut.rag.embedder import Embedder, HashingEmbedder
from sut.rag.loader import SourceDocument
from sut.rag.store import InMemoryVectorStore, Metric, SearchHit

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "i",
    "my",
    "me",
    "you",
    "your",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "and",
    "or",
    "it",
    "what",
    "when",
    "how",
    "can",
    "get",
    "be",
    "am",
    "has",
}


def _stem(token: str) -> str:
    """Tiny plural stemmer - good enough for lexical overlap metrics."""
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


# small query-expansion map: common question vocabulary -> corpus vocabulary
_SYNONYMS = {
    "maximum": {"cap", "limit"},
    "compensation": {"credit"},
    "arrive": {"post", "issue"},
    "kept": {"retained"},
    "store": {"stored"},
    "fast": {"hours"},
    "reshipped": {"reshipped", "lost"},
    "delete": {"deletion"},
    "threatened": {"threat"},
}


def content_words(text: str) -> set[str]:
    """Lowercased, stemmed content tokens (stopwords removed) for lexical metrics."""
    return {
        _stem(token)
        for token in _WORD_RE.findall(text.lower())
        if token not in _STOPWORDS and len(token) > 1
    }


def expanded_question_words(question: str) -> set[str]:
    """Content words of the question plus their synonyms (query expansion)."""
    words = content_words(question)
    expanded = set(words)
    for word in words:
        expanded |= _SYNONYMS.get(word, set())
    return expanded


@dataclass(slots=True)
class ScoredChunk:
    """A retrieved chunk with its score and source."""

    chunk: Chunk
    score: float
    rank: int


@dataclass(slots=True)
class RagAnswer:
    """One RAG turn: question, retrieved context, generated answer."""

    question: str
    answer: str
    contexts: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    answered: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "answered": self.answered,
            "sources": self.sources,
            "top_score": self.scores[0] if self.scores else 0.0,
        }


class RetrievalPipeline:
    """Build once from documents; query many times."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder: Embedder = embedder if embedder is not None else HashingEmbedder()
        self.store = InMemoryVectorStore()
        self.chunks: dict[str, Chunk] = {}
        self.documents: dict[str, SourceDocument] = {}
        self.config: dict[str, Any] = {}

    # ------------------------------------------------------------------ build
    def build(
        self,
        documents: list[SourceDocument],
        *,
        strategy: Strategy = "recursive",
        size: int = 2048,
        overlap: int = 0,
    ) -> dict[str, Any]:
        """Chunk, embed and index every document; return build stats."""
        self.store = InMemoryVectorStore()
        self.chunks = {}
        self.documents = {doc.doc_id: doc for doc in documents}
        chunks = chunk_documents(documents, strategy, size=size, overlap=overlap)
        for chunk in chunks:
            vector = self.embedder.embed(chunk.text)
            self.chunks[chunk.chunk_id] = chunk
            self.store.add(
                chunk.chunk_id,
                vector,
                {"doc_id": chunk.doc_id, "strategy": chunk.strategy, "preview": chunk.text[:80]},
            )
        self.config = {
            "strategy": strategy,
            "size": size,
            "overlap": overlap,
            "embedder": self.embedder.name,
            "documents": len(documents),
            "chunks": len(chunks),
        }
        return self.config

    # ------------------------------------------------------------------ query
    def query(self, text: str, k: int = 5, metric: Metric = "cosine") -> list[ScoredChunk]:
        hits: list[SearchHit] = self.store.search(self.embedder.embed(text), k=k, metric=metric)
        return [
            ScoredChunk(chunk=self.chunks[hit.item_id], score=hit.score, rank=rank + 1)
            for rank, hit in enumerate(hits)
        ]

    def answer(self, question: str, k: int = 4, metric: Metric = "cosine") -> RagAnswer:
        """Retrieve context, then answer extractively (or decline)."""
        hits = self.query(question, k=k, metric=metric)
        contexts = [hit.chunk.text for hit in hits]
        sources = [hit.chunk.doc_id for hit in hits]
        scores = [hit.score for hit in hits]
        best_sentence, source = self._best_supported_sentence(question, hits)
        if best_sentence is None:
            return RagAnswer(
                question=question,
                answer=("I don't know - that isn't covered by the policy documents I have."),
                contexts=contexts,
                scores=scores,
                sources=sources,
                answered=False,
            )
        return RagAnswer(
            question=question,
            answer=best_sentence,
            contexts=contexts,
            scores=scores,
            sources=sorted({source, *[s for s in sources if s == source]}),
            answered=True,
        )

    # -------------------------------------------------------------- internals
    def _best_supported_sentence(
        self, question: str, hits: list[ScoredChunk]
    ) -> tuple[str | None, str]:
        """Best context sentence by keyword overlap; headings only as fallback."""
        question_words = expanded_question_words(question)
        if not question_words:
            return None, ""
        best_sentence: tuple[float, str, str] | None = None
        best_heading: tuple[float, str, str] | None = None
        for hit in hits:
            for raw in re.split(r"(?<=[.!?])\s+", hit.chunk.text):
                is_heading = raw.lstrip().startswith("#")
                sentence = raw.strip().lstrip("#").strip()
                if not sentence:
                    continue
                overlap = float(len(question_words & content_words(sentence)))
                if overlap < 2:
                    continue
                entry = (overlap, sentence, hit.chunk.doc_id)
                if is_heading:
                    if best_heading is None or overlap > best_heading[0]:
                        best_heading = entry
                elif best_sentence is None or overlap > best_sentence[0]:
                    best_sentence = entry
        chosen = best_sentence or best_heading
        if chosen is None:
            return None, ""
        return chosen[1], chosen[2]
