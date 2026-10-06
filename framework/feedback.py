"""Feedback-to-test pipeline (PRD-3).

Thumbs up/down and retry signals are triaged weekly and promoted into the
regression set: failures become new golden cases in
``datasets/golden/from_feedback.csv`` (consumed by the L2/L5 suites) and the
pipeline log records the promotion for audit.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from sut.policy import parse_amount


def load_feedback(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("question")]


def triage(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Cluster failure signals by (action_taken, sentiment, retried)."""
    total = len(rows)
    down = [row for row in rows if row.get("sentiment") == "down"]
    retried = [row for row in rows if str(row.get("retried", "")).lower() in {"1", "true", "yes"}]
    clusters: dict[str, list[dict[str, str]]] = {}
    for row in down + retried:
        key = (
            f"{row.get('action_taken', 'unknown')}"
            f"-sentiment:{row.get('sentiment', '?')}"
            f"-retried:{row.get('retried', '?')}"
        )
        clusters.setdefault(key, []).append(row)
    return {
        "total_signals": total,
        "thumbs_down": len(down),
        "retries": len(retried),
        "clusters": {key: len(rows_) for key, rows_ in clusters.items()},
    }


def _expected_for(question: str) -> str:
    """Derive the expected action for a promoted case (the policy answer)."""
    from sut.policy import MAX_REFUND_PAISE, AmountParsingError

    try:
        amount = parse_amount(question)
    except AmountParsingError:
        return "ask_info"
    return "approve" if amount <= MAX_REFUND_PAISE else "refuse"


_FORMULA_PREFIXES = ("=", "+", "-", "@", chr(9), chr(13))


def csv_safe_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection (audit E1).

    Cells derived from untrusted text that start with =, +, -, @ or a
    tab/CR get a leading apostrophe so Excel/LibreOffice treat them as
    text instead of formulas/DDE payloads.
    """
    stripped = value.lstrip()
    if stripped.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def promote_to_regression(rows: list[dict[str, str]], out_path: str | Path) -> list[dict[str, str]]:
    """Turn failure signals into golden regression rows (deduped by question)."""
    promoted: list[dict[str, str]] = []
    seen: set[str] = set()
    existing: set[str] = set()
    out_path = Path(out_path)
    if out_path.exists():
        with out_path.open(newline="", encoding="utf-8") as handle:
            existing = {row["text"] for row in csv.DictReader(handle)}
    for row in rows:
        question = row.get("question", "").strip()
        if not question or question in seen or question in existing:
            continue
        if row.get("sentiment") != "down" and str(row.get("retried", "")).lower() not in {
            "1",
            "true",
            "yes",
        }:
            continue  # only failures are promoted
        seen.add(question)
        promoted.append(
            {
                "case_id": f"fb-{len(existing) + len(promoted) + 1:03d}",
                "text": csv_safe_cell(question),
                "order_id": csv_safe_cell(row.get("order_id", "").strip()),
                "expected_action": _expected_for(question),
                "category": "from_feedback",
            }
        )
    if promoted:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not out_path.exists()
        with out_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["case_id", "text", "order_id", "expected_action", "category"]
            )
            if write_header:
                writer.writeheader()
            writer.writerows(promoted)
    return promoted


def run_feedback_cycle(
    feedback_csv: str | Path,
    golden_out: str | Path,
    log_path: str | Path = "reports/feedback_cycle.json",
) -> dict[str, Any]:
    """One weekly cycle: load -> triage -> promote -> log (PRD-3 evidence)."""
    rows = load_feedback(feedback_csv)
    summary = triage(rows)
    promoted = promote_to_regression(rows, golden_out)
    log = summary | {
        "cycle_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "promoted_cases": [row["case_id"] for row in promoted],
        "golden_path": str(golden_out),
    }
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return log
