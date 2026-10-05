"""Chunking strategies (blueprint Domain 4: chunk experiments).

Three strategies at several sizes and overlaps; every chunk carries the
strategy + parameters so retrieval benchmarks can compare configurations.
Sizes are characters (approximately 4 chars per token - the blueprint's token
sizes of 256/512/1024 map to 1024/2048/4096 chars).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from sut.rag.loader import SourceDocument

Strategy = Literal["fixed", "recursive", "sentence-window"]

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class Chunk(BaseModel):
    """One retrievable chunk."""

    chunk_id: str
    doc_id: str
    index: int
    text: str
    strategy: str
    size: int
    overlap: int

    @property
    def char_len(self) -> int:
        return len(self.text)


def chunk_document(
    document: SourceDocument,
    strategy: Strategy = "recursive",
    *,
    size: int = 2048,
    overlap: int = 0,
    window: int = 3,
) -> list[Chunk]:
    """Chunk one document with the given strategy."""
    if size < 50:
        msg = f"size must be >= 50 chars, got {size}"
        raise ValueError(msg)
    if not 0 <= overlap < size:
        msg = f"overlap must be in [0, size), got {overlap} for size {size}"
        raise ValueError(msg)
    if strategy == "fixed":
        pieces = _fixed(document.text, size, overlap)
    elif strategy == "recursive":
        pieces = _recursive(document.text, size, overlap)
    elif strategy == "sentence-window":
        pieces = _sentence_window(document.text, window, overlap)
    else:
        msg = f"unknown strategy {strategy!r}"
        raise ValueError(msg)
    return [
        Chunk(
            chunk_id=f"{document.doc_id}#{i}",
            doc_id=document.doc_id,
            index=i,
            text=piece,
            strategy=strategy,
            size=size,
            overlap=overlap,
        )
        for i, piece in enumerate(pieces)
        if piece.strip()
    ]


def chunk_documents(
    documents: list[SourceDocument],
    strategy: Strategy = "recursive",
    *,
    size: int = 2048,
    overlap: int = 0,
    window: int = 3,
) -> list[Chunk]:
    """Chunk every document."""
    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, strategy, size=size, overlap=overlap, window=window))
    return chunks


def _fixed(text: str, size: int, overlap: int) -> list[str]:
    step = size - overlap
    return [text[start : start + size] for start in range(0, len(text), step)] if text else []


def _recursive(text: str, size: int, overlap: int) -> list[str]:
    """Split on paragraph -> line -> sentence boundaries, packing to <= size."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    pieces: list[str] = []

    def pack(units: list[str]) -> None:
        current = ""
        for unit in units:
            candidate = f"{current} {unit}".strip() if current else unit
            if len(candidate) > size and current:
                pieces.append(current)
                current = unit if len(unit) <= size else unit[:size]
            else:
                current = candidate
        if current.strip():
            pieces.append(current)

    for paragraph in paragraphs:
        if len(paragraph) <= size:
            pack([paragraph])
            continue
        lines = [line for line in paragraph.splitlines() if line.strip()]
        if max(map(len, lines), default=0) <= size:
            pack(lines)
            continue
        sentences = [s for s in _SENTENCE_RE.split(paragraph) if s.strip()]
        pack(sentences)
    if overlap and len(pieces) > 1:
        pieces = _apply_overlap(pieces, overlap)
    return pieces if pieces else ([text] if text.strip() else [])


def _sentence_window(text: str, window: int, overlap: int) -> list[str]:
    if window < 1:
        msg = f"window must be >= 1, got {window}"
        raise ValueError(msg)
    sentences = [s.strip() for s in _SENTENCE_RE.split(text.replace("\n\n", " ")) if s.strip()]
    step = max(1, window - overlap_sentences(overlap))
    return [
        " ".join(sentences[start : start + window])
        for start in range(0, len(sentences), step)
        if sentences[start : start + window]
    ]


def overlap_sentences(overlap: int) -> int:
    """Overlap expressed in sentences (heuristic: one sentence per 120 chars)."""
    return max(0, overlap // 120)


def _apply_overlap(pieces: list[str], overlap: int) -> list[str]:
    """Prepend the tail of the previous piece to each piece (bounded)."""
    from itertools import pairwise

    result = [pieces[0]]
    for previous, piece in pairwise(pieces):
        tail = previous[-overlap:]
        result.append(f"{tail} {piece}".strip())
    return result
