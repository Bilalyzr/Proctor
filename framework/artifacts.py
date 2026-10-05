"""Artifact versioning for AST-1.

Prompts, configs, datasets, schemas and threshold files are hashed (SHA-256)
and linked to every run in a manifest, so any run can be reproduced against
the exact artifacts it executed with - the "versioned and linked to every run"
half of AST-1 (the other half is the run logger writing the manifest).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CHUNK_SIZE = 65536


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of a byte string."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 hex digest of a UTF-8 string (used for in-code prompts)."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    """SHA-256 hex digest of a file, streamed so large datasets are safe."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(roots: dict[str, str | Path]) -> dict[str, dict[str, str]]:
    """Hash every file under each named root.

    Returns ``{root_name: {"<relative/path>": "<sha256>", ...}}``. Missing roots
    raise FileNotFoundError - a run referencing a vanished artifact must fail,
    not silently skip it.
    """
    manifest: dict[str, dict[str, str]] = {}
    for name, root in roots.items():
        root_path = Path(root)
        if not root_path.exists():
            msg = f"artifact root {name!r} does not exist: {root_path}"
            raise FileNotFoundError(msg)
        entries: dict[str, str] = {}
        if root_path.is_file():
            entries[root_path.name] = sha256_file(root_path)
        else:
            for file in sorted(root_path.rglob("*")):
                if file.is_file():
                    entries[file.relative_to(root_path).as_posix()] = sha256_file(file)
        manifest[name] = entries
    return manifest


def manifest_digest(manifest: dict[str, dict[str, str]]) -> str:
    """Stable digest over a whole snapshot (order-independent)."""
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)
