#!/usr/bin/env python3
"""Stdlib task runner - the Makefile delegates here so Windows works too.

Usage: python scripts/tasks.py [setup|test|lint|gate|nightly|clean]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENV_PY = VENV_BIN = None  # set in main()


def _py() -> str:
    candidates = [REPO / ".venv" / "Scripts" / "python.exe", REPO / ".venv" / "bin" / "python"]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _run(args: list[str], **kwargs: object) -> int:
    print(f"$ {' '.join(args)}", flush=True)
    return subprocess.call(args, cwd=REPO, **kwargs)  # type: ignore[arg-type]


def task_setup() -> int:
    venv = REPO / ".venv"
    if not (venv / "Scripts" / "python.exe").exists() and not (venv / "bin" / "python").exists():
        rc = _run([sys.executable, "-m", "venv", str(venv)])
        if rc != 0:
            return rc
    py = _py()
    rc = _run([py, "-m", "pip", "install", "--upgrade", "pip"])
    if rc != 0:
        return rc
    return _run([py, "-m", "pip", "install", "-e", ".[dev]"])


def task_test() -> int:
    py = _py()
    # Full suite under coverage: pyproject's [tool.coverage.run] source lists ALL
    # packages and fail_under=85, so an l1-only run can never reach the gate.
    # Mirrors the L1 gate command in framework/gates.py (collecting the whole
    # tree also keeps the strict-markers guarantee across layer folders).
    return _run([py, "-m", "pytest", "tests", "-q", "--cov", "--cov-report=term-missing"])


def task_lint() -> int:
    py = _py()
    rc = _run([py, "-m", "ruff", "check", "framework", "clients", "sut", "tests", "scripts"])
    if rc != 0:
        return rc
    return _run([py, "-m", "mypy", "framework", "clients", "sut"])


def task_gate() -> int:
    py = _py()
    return _run([py, "-m", "framework.gate_runner"])  # installed by Phase 2


def task_nightly() -> int:
    py = _py()
    return _run([py, "-m", "pytest", "tests", "-q", "--cov"])


def task_clean() -> int:
    import shutil

    for name in (".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage", "htmlcov"):
        target = REPO / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    return 0


TASKS = {
    "setup": task_setup,
    "test": task_test,
    "lint": task_lint,
    "gate": task_gate,
    "nightly": task_nightly,
    "clean": task_clean,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in TASKS:
        print(__doc__)
        print("tasks:", ", ".join(sorted(TASKS)))
        return 2
    return TASKS[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
