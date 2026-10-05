"""Document loading for the RAG corpus (RAG-1 stage 1: parsed).

Markdown and text files parse natively; PDFs parse through ``pdf_lite`` (or
pypdf when installed). Every document carries the counters the ingestion
verification gate asserts on: words, headings, pages.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from sut.rag import pdf_lite

_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_PAGE_RE = re.compile(rb"/Type\s*/Page[^s]")


class SourceDocument(BaseModel):
    """One parsed policy document."""

    doc_id: str
    source: str
    title: str
    text: str
    format: str
    word_count: int
    headings_count: int
    pages: int = Field(default=1, ge=1)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


def _parse_markdown(path: Path) -> SourceDocument:
    text = path.read_text(encoding="utf-8")
    first_heading = next(
        (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
        path.stem,
    )
    return SourceDocument(
        doc_id=path.stem,
        source=path.as_posix(),
        title=first_heading,
        text=text,
        format=path.suffix.lstrip("."),
        word_count=len(text.split()),
        headings_count=len(_HEADING_RE.findall(text)),
    )


def _parse_pdf(path: Path) -> SourceDocument:
    text = pdf_lite.extract_text(path.read_bytes())
    first_line = next((line for line in text.splitlines() if line.strip()), path.stem)
    pages = max(1, len(_PAGE_RE.findall(path.read_bytes())))
    return SourceDocument(
        doc_id=path.stem,
        source=path.as_posix(),
        title=first_line,
        text=text,
        format="pdf",
        word_count=len(text.split()),
        headings_count=sum(
            1 for line in text.splitlines() if line.strip() and line.strip()[-1] != "."
        ),
        pages=pages,
    )


_PARSERS = {
    ".md": _parse_markdown,
    ".markdown": _parse_markdown,
    ".txt": _parse_markdown,
    ".pdf": _parse_pdf,
}


def load_documents(root: str | Path) -> tuple[list[SourceDocument], list[str]]:
    """Load every supported document under ``root`` (recursive, sorted).

    Returns (documents, skipped_sources); unsupported extensions are skipped
    with a reason, never silently dropped - RAG-1 requires accounting for
    every source file.
    """
    documents: list[SourceDocument] = []
    skipped: list[str] = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        parser = _PARSERS.get(path.suffix.lower())
        if parser is None:
            skipped.append(f"{path.as_posix()}: unsupported extension {path.suffix}")
            continue
        documents.append(parser(path))
    return documents, skipped
