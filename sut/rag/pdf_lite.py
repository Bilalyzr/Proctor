"""Minimal PDF support for the offline RAG corpus.

The blueprint's retrieval stack normally uses Unstructured/pypdf; those are
optional here (see ``pypdf_available``). What ships by default is a *real but
small* PDF subset:

* :func:`write_pdf` emits a valid single-font, uncompressed PDF (what a
  policy-export tool might produce);
* :func:`extract_text` parses that subset genuinely - content streams,
  ``Tj`` text operators, PDF string escaping, and ``T*``/``Td`` line breaks.

Compressed or exotic PDFs raise :class:`PdfUnsupported` with a clear message
instead of returning garbage text.
"""

from __future__ import annotations

import re
from pathlib import Path

_STREAM_RE = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
_STRING_RE = re.compile(r"\((?:[^()\\]|\\.)*\)", re.DOTALL)
# ordered walk: "..." Tj | [ ... ] TJ | T* | x y Td/TD  (line breaks)
_TOKEN_RE = re.compile(
    r"(\((?:[^()\\]|\\.)*\))\s*Tj"
    r"|\[((?:[^\[\]]|\\.)*)\]\s*TJ"
    r"|\bT\*"
    r"|\b\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s+T[dD]\b",
    re.DOTALL,
)


class PdfUnsupported(ValueError):
    """The PDF uses features outside the supported (uncompressed) subset."""


def pypdf_available() -> bool:
    """True when the optional pypdf dependency is installed."""
    import importlib.util

    return importlib.util.find_spec("pypdf") is not None


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(path: str | Path, title: str, lines: list[str], *, font_size: int = 11) -> bytes:
    """Write a valid uncompressed single-page-per-45-lines PDF; return bytes."""
    page_lines = [lines[i : i + 45] for i in range(0, len(lines), 45)] or [[]]
    objects: list[bytes] = []

    def obj(body: str) -> int:
        objects.append(body.encode("utf-8"))
        return len(objects)

    font_id = obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    content_ids: list[int] = []
    for group in page_lines:
        parts = ["BT", f"/F1 {font_size} Tf", "14 14 Td", "1.35 TL"]
        for line in group:
            parts.append(f"({_escape(line)}) Tj")
            parts.append("T*")
        parts.append("ET")
        stream = "\n".join(parts)
        content_ids.append(obj(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"))
    pages_id_placeholder = len(objects) + len(page_lines) + 1
    for content_id in content_ids:
        page_ids.append(
            obj(
                f"<< /Type /Page /Parent {pages_id_placeholder} 0 R "
                f"/MediaBox [0 0 595 842] /Contents {content_id} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            )
        )
    pages_id = obj(
        f"<< /Type /Pages /Kids [{' '.join(f'{pid} 0 R' for pid in page_ids)}] "
        f"/Count {len(page_ids)} >>"
    )
    assert pages_id == pages_id_placeholder, "object numbering drifted"
    catalog_id = obj(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")
    info_id = obj(f"<< /Title ({_escape(title)}) /Producer (proctor pdf_lite) >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R "
        f"/Info {info_id} 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    Path(path).write_bytes(bytes(out))
    return bytes(out)


def _unescape(pdf_string: str) -> str:
    body = pdf_string[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        char = body[i]
        if char != "\\":
            out.append(char)
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < len(body) else ""
        simple = {"n": "\n", "r": "\r", "t": "\t", "(": "(", ")": ")", "\\": "\\"}
        if nxt in simple:
            out.append(simple[nxt])
            i += 2
        elif nxt.isdigit():
            octal = body[i + 1 : i + 4]
            try:
                out.append(chr(int(octal, 8)))
                i += 1 + len(octal)
            except ValueError:  # pragma: no cover - malformed escape
                out.append(nxt)
                i += 2
        else:
            out.append(nxt)
            i += 2
    return "".join(out)


def extract_text(data: bytes) -> str:
    """Extract text from an uncompressed PDF's content streams."""
    if b"/FlateDecode" in data or b"/ObjStm" in data:
        if pypdf_available():  # pragma: no cover - optional dependency path
            import io

            from pypdf import PdfReader  # type: ignore[import-not-found]

            return "\n".join(
                page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages
            )
        msg = "compressed PDF: install pypdf ('proctor[pdf]') or use an uncompressed export"
        raise PdfUnsupported(msg)
    lines: list[str] = []
    for stream in _STREAM_RE.findall(data):
        text = stream.decode("latin-1")
        pieces: list[str] = []
        for match in _TOKEN_RE.finditer(text):
            token = match.group(0)
            if token.endswith("Tj"):
                pieces.append(_unescape(match.group(1) or ""))
            elif token.endswith("TJ"):
                pieces.extend(_unescape(s.group(0)) for s in _STRING_RE.finditer(token))
            else:  # T* or Td/TD: line break
                if pieces:
                    lines.append(" ".join(pieces))
                    pieces = []
        if pieces:
            lines.append(" ".join(pieces))
    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        msg = "no extractable text found (unsupported PDF subset)"
        raise PdfUnsupported(msg)
    return "\n".join(cleaned)
