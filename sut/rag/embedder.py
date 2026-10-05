"""Embedding interface + deterministic offline embedder.

``HashingEmbedder`` maps character trigrams into a fixed-width space via
blake2b hashing and L2-normalizes - fully deterministic, dependency-free, and
good enough for lexical retrieval benchmarks on a small policy corpus. Real
embeddings (sentence-transformers etc.) slot in behind the same protocol and
activate when installed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import re
from typing import Protocol

_TOKEN_CLEAN_RE = re.compile(r"[^a-z0-9\u0900-\u097f\u20b9 ]+")


class Embedder(Protocol):
    """The interface every embedding backend implements."""

    @property
    def name(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic hashed character-trigram embeddings."""

    def __init__(self, dim: int = 512) -> None:
        if dim < 16:
            msg = f"dim must be >= 16, got {dim}"
            raise ValueError(msg)
        self._dim = dim

    @property
    def name(self) -> str:
        return f"hashing-trigram-d{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        normalized = _TOKEN_CLEAN_RE.sub(" ", text.lower()).strip()
        vector = [0.0] * self._dim
        if not normalized:
            return vector
        padded = f"  {normalized}  "
        for i in range(len(padded) - 2):
            trigram = padded[i : i + 3]
            digest = hashlib.blake2b(trigram.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self._dim
            vector[index] += 1.0
        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0.0:  # pragma: no cover - nonzero input always hashes somewhere
            return vector
        return [component / norm for component in vector]


class EmbedderUnavailable(RuntimeError):
    """A real embedding backend was requested but is not installed."""


class SentenceTransformerEmbedder:
    """Optional backend: activates when sentence-transformers is installed."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        if importlib.util.find_spec("sentence_transformers") is None:
            msg = "sentence-transformers not installed; using HashingEmbedder offline"
            raise EmbedderUnavailable(msg)
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        self._model = SentenceTransformer(model_name)  # pragma: no cover
        self._dim = self._model.get_sentence_embedding_dimension() or 384  # pragma: no cover

    @property
    def name(self) -> str:
        return "sentence-transformers"  # pragma: no cover

    @property
    def dim(self) -> int:
        return self._dim  # pragma: no cover

    def embed(self, text: str) -> list[float]:
        return [float(v) for v in self._model.encode(text)]  # pragma: no cover


def default_embedder() -> Embedder:
    """Offline default; upgrades to sentence-transformers when available."""
    if importlib.util.find_spec("sentence_transformers") is not None:  # pragma: no cover
        try:
            return SentenceTransformerEmbedder()
        except EmbedderUnavailable:
            pass
    return HashingEmbedder()
