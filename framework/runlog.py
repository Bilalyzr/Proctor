"""Structured run logging (AST-1 / GOV-3 groundwork).

Every test run writes one JSON-lines file: a ``run_start`` header carrying the
run ID, generation parameters and an artifact-hash manifest, one record per
case, and a ``run_end`` footer with the summary. Downstream tooling (dashboards,
evidence packs, the traceability report) consumes only these files.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from framework.artifacts import manifest_digest

RecordStatus = str  # "pass" | "fail" | "error" | "skip" | "info"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class RunLogger:
    """Append-only JSONL run logger."""

    def __init__(
        self,
        log_dir: str | Path,
        suite: str,
        run_id: str | None = None,
        params: dict[str, Any] | None = None,
        artifacts: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.run_id = run_id or f"{suite}-{uuid.uuid4().hex[:12]}"
        self.suite = suite
        self.log_dir = Path(log_dir)
        self.runs_dir = self.log_dir / "runs"
        self.manifests_dir = self.log_dir / "manifests"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.runs_dir / f"{self.run_id}.jsonl"
        self._counts: dict[str, int] = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
        self._start = time.monotonic()
        self._handle: TextIO | None = None
        self._params = dict(params or {})
        self._artifacts = artifacts or {}
        self._closed = False

    # -- context management -------------------------------------------------
    def __enter__(self) -> RunLogger:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- lifecycle -----------------------------------------------------------
    def open(self) -> None:
        """Write the run_start header (idempotent)."""
        if self._handle is not None:
            return
        self._handle = self.path.open("w", encoding="utf-8")
        self._write(
            "run_start",
            suite=self.suite,
            started_at=_utc_now(),
            params=self._params,
            artifact_digest=manifest_digest(self._artifacts) if self._artifacts else None,
        )
        if self._artifacts:
            manifest_path = self.manifests_dir / f"{self.run_id}.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "run_id": self.run_id,
                        "suite": self.suite,
                        "created_at": _utc_now(),
                        "artifacts": self._artifacts,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

    def close(self) -> dict[str, Any]:
        """Write the run_end footer, flush, and return the summary."""
        if self._closed:
            return self.summary()
        if self._handle is None:
            self.open()
        assert self._handle is not None
        duration_s = round(time.monotonic() - self._start, 6)
        summary = self.summary() | {"duration_s": duration_s, "ended_at": _utc_now()}
        self._write("run_end", **summary)
        self._handle.flush()
        self._handle.close()
        self._handle = None
        self._closed = True
        return summary

    # -- records ---------------------------------------------------------------
    def log_case(
        self,
        case_id: str,
        status: RecordStatus,
        layer: str = "",
        details: dict[str, Any] | None = None,
        req_ids: list[str] | None = None,
    ) -> None:
        """Record one case outcome; unknown statuses are counted as errors."""
        if self._handle is None:
            self.open()
        count_key = status if status in self._counts else "error"
        self._counts[count_key] += 1
        record: dict[str, Any] = {
            "case_id": case_id,
            "status": status,
            "ts": _utc_now(),
        }
        if layer:
            record["layer"] = layer
        if details:
            record["details"] = details
        if req_ids:
            record["req_ids"] = req_ids
        assert self._handle is not None
        self._write("case", **record)

    def summary(self) -> dict[str, Any]:
        """Current counts (and duration once closed)."""
        total = sum(self._counts.values())
        return {"run_id": self.run_id, "suite": self.suite, "total": total} | {
            f"{k}_count": v for k, v in self._counts.items()
        }

    # -- internals --------------------------------------------------------------
    def _write(self, record_type: str, **payload: Any) -> None:
        assert self._handle is not None
        line = json.dumps({"type": record_type, **payload}, sort_keys=True, default=str)
        self._handle.write(line + "\n")


def read_run(path: str | Path) -> list[dict[str, Any]]:
    """Read back a run log as a list of records."""
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records
