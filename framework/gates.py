"""Layer-gate machinery: ordered pyramid execution against thresholds (Rule 3).

A lower layer must pass before higher layers run: a *failure* stops the climb
immediately. Layers not yet built by the current roadmap phase are recorded as
``not_built`` and the climb continues past them - they are not gates yet, and
the pyramid only ever extends upward.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.thresholds import ThresholdFile

# Bumped as each build phase lands its layer (P5 adds l3 and l7).
IMPLEMENTED_LAYERS: tuple[str, ...] = ("l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9")

LAYER_COMMANDS: dict[str, list[str]] = {
    # EVL-5 measures branch coverage over all non-AI logic, which the whole
    # deterministic suite exercises - so the L1 gate step runs everything
    # under coverage. Higher layers select by MARKER across the whole test
    # tree, so suites can live anywhere (including tests/domains/) and still
    # ride their pyramid layer.
    "l1": [
        "-m",
        "pytest",
        "tests",
        "-q",
        "--cov",
        "--cov-report=json:reports/coverage.json",
    ],
    "l2": ["-m", "pytest", "tests", "-m", "l2", "-q"],
    "l3": ["-m", "pytest", "tests", "-m", "l3", "-q"],
    "l4": ["-m", "pytest", "tests", "-m", "l4", "-q"],
    "l5": ["-m", "pytest", "tests", "-m", "l5", "-q"],
    "l6": ["-m", "pytest", "tests", "-m", "l6", "-q"],
    "l7": ["-m", "pytest", "tests", "-m", "l7", "-q"],
    "l8": ["-m", "pytest", "tests", "-m", "l8", "-q"],
    "l9": ["-m", "pytest", "tests", "-m", "l9", "-q"],
}

Executor = Callable[[Sequence[str]], int]


@dataclass(slots=True)
class LayerResult:
    """Outcome of one layer's gate check."""

    layer: str
    status: str  # "pass" | "fail" | "not_built" | "skipped"
    duration_s: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "status": self.status,
            "duration_s": self.duration_s,
            "details": self.details,
        }


@dataclass(slots=True)
class GateVerdict:
    """Full pyramid verdict."""

    passed: bool
    stopped_at: str
    results: list[LayerResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "stopped_at": self.stopped_at,
            "results": [r.as_dict() for r in self.results],
        }


def subprocess_executor(command: Sequence[str]) -> int:
    """Default executor: run pytest via the current interpreter."""
    import sys

    rendered = [sys.executable, *command]
    return subprocess.call(rendered, cwd=Path.cwd())


def _read_coverage_percent(coverage_json: str | Path) -> float:
    data = json.loads(Path(coverage_json).read_text(encoding="utf-8"))
    return float(data["totals"]["percent_covered"])


def check_layer(
    layer: str,
    thresholds: ThresholdFile,
    *,
    executor: Executor = subprocess_executor,
    coverage_json: str | Path = "reports/coverage.json",
) -> LayerResult:
    """Run one layer's suite and apply its threshold gate."""
    started = time.monotonic()
    if layer not in IMPLEMENTED_LAYERS:
        return LayerResult(layer, "not_built", 0.0, {"reason": "layer not built yet"})
    command = LAYER_COMMANDS[layer]
    code = executor(command)
    duration = round(time.monotonic() - started, 3)
    if code != 0:
        return LayerResult(layer, "fail", duration, {"exit_code": code, "command": list(command)})
    details: dict[str, Any] = {"exit_code": 0}
    if layer == "l1":
        minimum = thresholds.gate_value("l1", "min_branch_coverage") * 100.0
        try:
            percent = _read_coverage_percent(coverage_json)
        except (OSError, KeyError, ValueError) as exc:
            return LayerResult(layer, "fail", duration, {"error": f"coverage unreadable: {exc}"})
        details["branch_coverage"] = round(percent, 2)
        details["min_branch_coverage"] = round(minimum, 2)
        if percent < minimum:
            return LayerResult(layer, "fail", duration, details)
    return LayerResult(layer, "pass", duration, details)


def run_gates(
    thresholds: ThresholdFile,
    *,
    layers: Sequence[str] = ("l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9"),
    executor: Executor = subprocess_executor,
    coverage_json: str | Path = "reports/coverage.json",
) -> GateVerdict:
    """Climb the pyramid bottom-up; a failure stops the climb immediately."""
    results: list[LayerResult] = []
    stopped_at = "complete"
    for layer in layers:
        result = check_layer(layer, thresholds, executor=executor, coverage_json=coverage_json)
        results.append(result)
        if result.status == "fail":
            stopped_at = layer
            break
    failed = any(r.status == "fail" for r in results)
    return GateVerdict(passed=not failed, stopped_at=stopped_at, results=results)


def write_verdict(verdict: GateVerdict, reports_dir: str | Path = "reports") -> Path:
    """Persist the verdict JSON (plus a latest.json pointer)."""
    directory = Path(reports_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = directory / f"gate_verdict_{stamp}.json"
    payload = {"written_at": stamp, **verdict.as_dict()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (directory / "latest_gate_verdict.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return path
