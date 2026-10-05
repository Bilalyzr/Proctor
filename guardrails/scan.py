"""Repository scanners (SEC-2): secrets in source, non-localhost bindings.

Deterministic, dependency-free stand-ins for gitleaks/trufflehog and nmap on
the specific surfaces this repo controls: tracked text files for secret
shapes, and source analysis for socket bindings (the MCP server is stdio-only
by design; if anything starts binding 0.0.0.0 these checks fail).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SECRET_SHAPES: list[tuple[str, re.Pattern[str]]] = [
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9-]{20,}\b")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "dotenv-assignment",
        re.compile(r"(?i)^(?:API_KEY|SECRET|PASSWORD|TOKEN)\s*=\s*(?!\s*\$\{)[^\s#]{8,}", re.M),
    ),
]

ALLOWED_FILES = {".env.example"}  # documented placeholders only
SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".pytest_cache", "reports", "datasets"}

BIND_PATTERNS = [
    re.compile(r"\.bind\(\s*\(?\s*[\"'](0\.0\.0\.0|::)[\"']"),
    re.compile(r"host\s*=\s*[\"']0\.0\.0\.0[\"']"),
]


def scan_secrets(root: str | Path) -> dict[str, Any]:
    """Scan tracked text files for secret shapes; return findings + summary."""
    findings: list[dict[str, str]] = []
    scanned = 0
    for path in Path(root).rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in ALLOWED_FILES:
            continue
        if path.suffix.lower() not in {
            ".py",
            ".yaml",
            ".yml",
            ".json",
            ".toml",
            ".md",
            ".txt",
            ".html",
            ".cfg",
            ".ini",
            ".csv",
        }:
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable files are skipped
            continue
        for rule, pattern in SECRET_SHAPES:
            for match in pattern.finditer(text):
                findings.append(
                    {"file": path.as_posix(), "rule": rule, "fragment": match.group(0)[:8] + "..."}
                )
    return {
        "scanned_files": scanned,
        "findings": findings,
        "critical_findings": len(findings),
        "status": "pass" if not findings else "fail",
    }


def scan_bindings(root: str | Path) -> dict[str, Any]:
    """Fail if any source file binds a public interface."""
    violations: list[dict[str, str]] = []
    scanned = 0
    for path in Path(root).rglob("*.py"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in BIND_PATTERNS:
            for match in pattern.finditer(text):
                violations.append({"file": path.as_posix(), "match": match.group(0)})
    return {
        "scanned_files": scanned,
        "public_binds": violations,
        "status": "pass" if not violations else "fail",
        "note": "the MCP server is stdio-only; the FastAPI app binds localhost in dev",
    }
