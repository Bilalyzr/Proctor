"""Metrics registry with Prometheus text export (PRD-2 groundwork).

Counters and gauges with labeled dimensions; ``render_prometheus()`` emits
the standard exposition format for scraping (or offline: for dashboard
snapshots). OpenTelemetry wires in behind the same record_* methods when
installed - ``otel_available()`` reports the truth.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def otel_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("opentelemetry.sdk") is not None


def _render_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    return "{" + inner + "}"


class MetricsRegistry:
    """In-process counters/gauges with a Prometheus text render."""

    def __init__(self, prefix: str = "aiqa") -> None:
        self.prefix = prefix
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._help: dict[str, str] = {
            "guardrail_blocks_total": "guardrail blocks by rule",
            "requests_total": "assistant requests by outcome",
            "accuracy": "golden-slice accuracy gauge",
            "context_precision": "RAG context precision gauge",
            "latency_p95_ms": "p95 latency gauge",
        }

    # ------------------------------------------------------------------ record
    def record_counter(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        self._counters[key] += value

    def record_gauge(self, name: str, value: float, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        self._gauges[key] = value

    # ------------------------------------------------------------------ render
    def render_prometheus(self) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for (name, _), value in sorted(self._counters.items()):
            if name not in seen:
                seen.add(name)
                lines.append(f"# HELP {self.prefix}_{name} {self._help.get(name, name)}")
                lines.append(f"# TYPE {self.prefix}_{name} counter")
            labels = dict(_)
            lines.append(f"{self.prefix}_{name}{_render_labels(labels)} {value}")
        for (name, label_pairs), value in sorted(self._gauges.items()):
            if name not in seen:
                seen.add(name)
                lines.append(f"# HELP {self.prefix}_{name} {self._help.get(name, name)}")
                lines.append(f"# TYPE {self.prefix}_{name} gauge")
            lines.append(f"{self.prefix}_{name}{_render_labels(dict(label_pairs))} {value}")
        return "\n".join(lines) + ("\n" if lines else "")

    def snapshot(self) -> dict[str, Any]:
        return {
            "counters": [
                {"name": name, "labels": dict(labels), "value": value}
                for (name, labels), value in sorted(self._counters.items())
            ],
            "gauges": [
                {"name": name, "labels": dict(labels), "value": value}
                for (name, labels), value in sorted(self._gauges.items())
            ],
        }
