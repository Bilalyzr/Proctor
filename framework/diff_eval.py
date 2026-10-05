"""Differential evaluation (GOV-5): old vs new model/parameters, go/no-go.

Runs the same golden slice under two configurations (provider, model,
temperature, seed - anything expressible as generation params) and compares
per-category accuracy; any critical-category regression blocks the swap.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clients.mock import MockClient
from framework.config import Settings
from sut.agent import RefundAssistant


@dataclass(slots=True)
class DiffReport:
    """Result of one A/B differential run."""

    label_a: str
    label_b: str
    accuracy_a: float
    accuracy_b: float
    by_category_a: dict[str, float]
    by_category_b: dict[str, float]
    decision: str  # "go" | "no-go"

    def as_dict(self) -> dict[str, Any]:
        return {
            "label_a": self.label_a,
            "label_b": self.label_b,
            "accuracy_a": round(self.accuracy_a, 4),
            "accuracy_b": round(self.accuracy_b, 4),
            "by_category_a": self.by_category_a,
            "by_category_b": self.by_category_b,
            "decision": self.decision,
        }


def load_slice(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _measure(
    cases: list[dict[str, str]],
    make_assistant: Callable[[], RefundAssistant],
) -> tuple[float, dict[str, list[int]]]:
    by_category: dict[str, list[int]] = {}
    correct = 0
    for case in cases:
        assistant = make_assistant()
        turn = assistant.handle(case["text"], order_id=case["order_id"] or None)
        ok = turn.decision.action.value == case["expected_action"]
        correct += int(ok)
        by_category.setdefault(case["category"], []).append(int(ok))
    accuracy = correct / len(cases) if cases else 0.0
    return accuracy, by_category


def _category_rates(by_category: dict[str, list[int]]) -> dict[str, float]:
    return {
        category: round(sum(results) / len(results), 4) for category, results in by_category.items()
    }


CRITICAL_CATEGORIES = {"boundary", "injection", "split"}


def run_differential(
    golden_path: str | Path,
    *,
    config_a: dict[str, Any],
    config_b: dict[str, Any],
    label_a: str = "current",
    label_b: str = "candidate",
    max_critical_regression: float = 0.0,
) -> DiffReport:
    """Compare two configurations on the same golden slice (GOV-5)."""
    cases = load_slice(golden_path)

    def make(config: dict[str, Any]) -> Callable[[], RefundAssistant]:
        def factory() -> RefundAssistant:
            settings = Settings(_env_file=None, **config)
            client = MockClient(settings.model_name_for("mock"), seed=settings.seed)
            return RefundAssistant(client, settings=settings)

        return factory

    accuracy_a, cats_a = _measure(cases, make(config_a))
    accuracy_b, cats_b = _measure(cases, make(config_b))
    rates_a = _category_rates(cats_a)
    rates_b = _category_rates(cats_b)

    critical_regression = any(
        rates_b.get(category, 0.0) < rates_a.get(category, 1.0) - max_critical_regression
        for category in CRITICAL_CATEGORIES
        if category in rates_a or category in rates_b
    )
    decision = "no-go" if critical_regression or accuracy_b < accuracy_a else "go"
    return DiffReport(
        label_a=label_a,
        label_b=label_b,
        accuracy_a=accuracy_a,
        accuracy_b=accuracy_b,
        by_category_a=rates_a,
        by_category_b=rates_b,
        decision=decision,
    )


def write_diff_report(report: DiffReport, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    return target
