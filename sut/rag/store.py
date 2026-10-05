"""Vector store interface + in-memory implementation (FAISS alternative).

Pure-Python cosine/Euclidean search over L2-normalized hashed embeddings -
fast enough for a policy corpus and fully deterministic. FAISS slots in
behind the same protocol when installed (blueprint: "FAISS or Qdrant or
pgvector behind an interface").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Metric = Literal["cosine", "euclidean"]


@dataclass(slots=True)
class SearchHit:
    """One search result with its similarity/distance score."""

    item_id: str
    score: float
    meta: dict[str, Any] = field(default_factory=dict)


class VectorStore(Protocol):
    def add(self, item_id: str, vector: list[float], meta: dict[str, Any]) -> None: ...

    def search(
        self, query_vector: list[float], k: int = 5, metric: Metric = "cosine"
    ) -> list[SearchHit]: ...

    def __len__(self) -> int: ...


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity; identical directions are 1.0, orthogonal 0.0."""
    na = math.sqrt(_dot(a, a))
    nb = math.sqrt(_dot(b, b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)


def euclidean_distance(a: list[float], b: list[float]) -> float:
    """Euclidean distance (smaller is more similar)."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


class InMemoryVectorStore:
    """Deterministic exact-search store (the offline FAISS stand-in)."""

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._vectors: list[list[float]] = []
        self._meta: list[dict[str, Any]] = []

    def add(self, item_id: str, vector: list[float], meta: dict[str, Any]) -> None:
        if not vector:
            msg = "cannot add an empty vector"
            raise ValueError(msg)
        self._ids.append(item_id)
        self._vectors.append(list(vector))
        self._meta.append(dict(meta))

    def search(
        self, query_vector: list[float], k: int = 5, metric: Metric = "cosine"
    ) -> list[SearchHit]:
        if k < 1:
            msg = f"k must be >= 1, got {k}"
            raise ValueError(msg)
        if len(query_vector) != len(next(iter(self._vectors), query_vector)):
            msg = "query dimensionality does not match the store"
            raise ValueError(msg)
        if metric == "cosine":
            scored = [
                (item_id, cosine_similarity(query_vector, stored), meta)
                for item_id, stored, meta in zip(self._ids, self._vectors, self._meta, strict=True)
            ]
            scored.sort(key=lambda hit: (-hit[1], hit[0]))  # score desc, id stable
            return [SearchHit(i, s, m) for i, s, m in scored[:k]]
        if metric == "euclidean":
            scored = [
                (item_id, euclidean_distance(query_vector, stored), meta)
                for item_id, stored, meta in zip(self._ids, self._vectors, self._meta, strict=True)
            ]
            scored.sort(key=lambda hit: (hit[1], hit[0]))  # distance asc
            return [SearchHit(i, s, m) for i, s, m in scored[:k]]
        msg = f"unknown metric {metric!r}"
        raise ValueError(msg)

    def __len__(self) -> int:
        return len(self._ids)
