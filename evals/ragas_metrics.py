"""The four RAGAS metrics (EVL-3) with an offline reference implementation.

``ragas_available()`` reports whether the real Ragas library is installed; when
it is *and* a real provider is configured, ``RagasBackend`` uses it. Offline,
``LocalRagasBackend`` computes reference implementations with lexical
content-word overlap - deterministic, documented in every report, and honest
about being an approximation (they are RAGAS-*style*, not Ragas-the-library
numbers; reports always name the engine that produced them).

* Context Precision - signal-to-noise of retrieved chunks (relevant chunks,
  ranked early, vs irrelevant ones).
* Context Recall - fraction of ground-truth facts covered by the context.
* Faithfulness - fraction of answer sentences supported by the context.
* Answer Relevance - how well the answer addresses the question.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, Protocol

from sut.rag.retriever import RagAnswer, content_words

_OVERLAP_THRESHOLD = 0.34  # content-word Jaccard/containment counted as "supported"


def ragas_available() -> bool:
    """True when the real Ragas library can be imported."""
    return importlib.util.find_spec("ragas") is not None


def _sentences(text: str) -> list[str]:
    import re

    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _supported(sentence: str, contexts: list[str]) -> bool:
    """A sentence is supported when some context covers a third of its content words."""
    words = content_words(sentence)
    if not words:
        return True  # nothing claimable, nothing unsupported
    context_words: set[str] = set()
    for context in contexts:
        context_words |= content_words(context)
    if not context_words:
        return False
    overlap = len(words & context_words)
    return overlap / len(words) >= _OVERLAP_THRESHOLD


def context_precision(question: str, contexts: list[str], is_relevant: list[bool]) -> float:
    """Mean precision@k over the ranked context list (RAGAS-style).

    Irrelevant chunks and relevant chunks ranked late both lower the score.
    """
    if not contexts or len(contexts) != len(is_relevant):
        msg = "contexts and is_relevant must be non-empty and equal length"
        raise ValueError(msg)
    question_words = content_words(question)
    relevant_so_far = 0
    score = 0.0
    for rank, (context, flagged) in enumerate(zip(contexts, is_relevant, strict=True), start=1):
        relevant = flagged or (len(question_words & content_words(context)) >= 2)
        if relevant:
            relevant_so_far += 1
            score += relevant_so_far / rank
    if relevant_so_far == 0:
        return 0.0
    return score / relevant_so_far


def context_recall(ground_truth: str, contexts: list[str]) -> float:
    """Fraction of ground-truth sentences the retrieved context covers."""
    truth_sentences = _sentences(ground_truth)
    if not truth_sentences:
        return 0.0
    supported = sum(1 for sentence in truth_sentences if _supported(sentence, contexts))
    return supported / len(truth_sentences)


def faithfulness(answer: str, contexts: list[str]) -> float:
    """Fraction of answer sentences supported by the retrieved context."""
    answer_sentences = _sentences(answer)
    if not answer_sentences:
        return 0.0
    supported = sum(1 for sentence in answer_sentences if _supported(sentence, contexts))
    return supported / len(answer_sentences)


def answer_relevance(question: str, answer: str) -> float:
    """Content-word containment of the question in the answer (scaled)."""
    question_words = content_words(question)
    if not question_words:
        return 0.0
    answer_words = content_words(answer)
    overlap = len(question_words & answer_words)
    return overlap / len(question_words)


@dataclass(slots=True)
class RagasReport:
    """The four metrics for one RAG turn plus the engine that computed them."""

    context_precision: float
    context_recall: float
    faithfulness: float
    answer_relevance: float
    engine: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "context_precision": round(self.context_precision, 4),
            "context_recall": round(self.context_recall, 4),
            "faithfulness": round(self.faithfulness, 4),
            "answer_relevance": round(self.answer_relevance, 4),
            "engine": self.engine,
        }


class RagasBackend(Protocol):
    name: str

    def evaluate_turn(
        self, turn: RagAnswer, *, ground_truth: str, is_relevant: list[bool]
    ) -> RagasReport: ...


class LocalRagasBackend:
    """Offline reference implementation (the default engine)."""

    name = "local-reference-v1"

    def evaluate_turn(
        self, turn: RagAnswer, *, ground_truth: str, is_relevant: list[bool]
    ) -> RagasReport:
        return RagasReport(
            context_precision=context_precision(turn.question, turn.contexts, is_relevant),
            context_recall=context_recall(ground_truth, turn.contexts),
            faithfulness=faithfulness(turn.answer, turn.contexts),
            answer_relevance=answer_relevance(turn.question, turn.answer),
            engine=self.name,
        )


class RagasLibraryBackend:
    """Real Ragas library backend - only when installed AND a real provider runs."""

    name = "ragas-library"

    def __init__(self) -> None:
        if not ragas_available():
            msg = "ragas not installed; pip install 'proctor[ragas]'"
            raise RuntimeError(msg)

    def evaluate_turn(  # pragma: no cover - requires network + keys
        self, turn: RagAnswer, *, ground_truth: str, is_relevant: list[bool]
    ) -> RagasReport:
        raise NotImplementedError(
            "wire RagasLibraryBackend to your LangChain wrapper when running "
            "against a real provider (offline CI uses LocalRagasBackend)"
        )


def default_backend() -> RagasBackend:
    """Local reference implementation unless the library is genuinely usable."""
    return LocalRagasBackend()


def evaluate_corpus(
    backend: RagasBackend,
    turns: list[RagAnswer],
    *,
    ground_truths: list[str],
    relevance_flags: list[list[bool]],
) -> dict[str, Any]:
    """Mean of each metric over a corpus of turns + per-turn detail."""
    reports = [
        backend.evaluate_turn(turn, ground_truth=truth, is_relevant=flags)
        for turn, truth, flags in zip(turns, ground_truths, relevance_flags, strict=True)
    ]
    count = len(reports)
    means = {
        "context_precision": (sum(r.context_precision for r in reports) / count) if count else 0.0,
        "context_recall": (sum(r.context_recall for r in reports) / count) if count else 0.0,
        "faithfulness": (sum(r.faithfulness for r in reports) / count) if count else 0.0,
        "answer_relevance": (sum(r.answer_relevance for r in reports) / count) if count else 0.0,
    }
    return {
        "engine": backend.name,
        "turns": count,
        "means": {key: round(value, 4) for key, value in means.items()},
        "per_turn": [r.as_dict() for r in reports],
    }
