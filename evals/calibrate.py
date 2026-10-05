"""Judge calibration against human labels (EVL-4).

Reads ``datasets/golden/judge_calibration.csv`` (question, expected_action,
human_score in [0,1]), replays each through the assistant + judge, and reports
Spearman rho between judge and human scores. The blueprint gate is rho >= 0.8.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.statistics import spearman_rho


@dataclass(slots=True)
class CalibrationRow:
    question: str
    expected_action: str
    human_score: float
    order_id: str | None = None


def load_calibration(path: str | Path) -> list[CalibrationRow]:
    rows: list[CalibrationRow] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            order_id = (row.get("order_id") or "").strip()
            rows.append(
                CalibrationRow(
                    question=row["question"],
                    expected_action=row["expected_action"],
                    human_score=float(row["human_score"]),
                    order_id=order_id if order_id and order_id != "ORD-" else None,
                )
            )
    if len(rows) < 5:
        msg = f"calibration set too small ({len(rows)} rows); need >= 5"
        raise ValueError(msg)
    return rows


def calibrate(judge_scores: list[float], human_scores: list[float]) -> dict[str, Any]:
    """Spearman agreement + per-bucket disagreement detail."""
    rho = spearman_rho(judge_scores, human_scores)
    big_disagreements = [
        index
        for index, (judge, human) in enumerate(zip(judge_scores, human_scores, strict=True))
        if abs(judge - human) > 0.5
    ]
    return {
        "n": len(judge_scores),
        "spearman_rho": round(rho, 4),
        "gate": "rho >= 0.8 (EVL-4)",
        "passed": rho >= 0.8,
        "big_disagreements": big_disagreements,
    }
