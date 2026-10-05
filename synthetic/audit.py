"""Validation and human-audit sampling for synthetic cases (AST-3)."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from synthetic.generator import GeneratedCase


def validate_cases(cases: list[dict[str, Any]]) -> tuple[list[GeneratedCase], list[dict[str, Any]]]:
    """Schema-validate raw case dicts; return (valid, rejected-with-reason)."""
    valid: list[GeneratedCase] = []
    rejected: list[dict[str, Any]] = []
    for raw in cases:
        try:
            valid.append(GeneratedCase.model_validate(raw))
        except ValidationError as exc:
            rejected.append(
                {"case": raw.get("case_id", "?"), "errors": exc.errors(include_url=False)}
            )
    return valid, rejected


def export_audit_sample(
    cases: list[GeneratedCase],
    *,
    sample_size: int = 30,
    seed: int = 42,
    out_dir: str | Path = "reports/audit",
) -> Path:
    """Export a seeded random sample for the weekly human audit (GOV-1/AST-3).

    Reviewers fill the ``human_verdict`` column (agree / disagree / unsafe);
    accepted samples graduate into the golden slice.
    """
    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    rng = random.Random(seed)
    sample = rng.sample(cases, k=min(sample_size, len(cases)))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "audit_sample.csv"
    columns = [
        "case_id",
        "text",
        "order_id",
        "expected_action",
        "category",
        "amount_paise",
        "intent",
        "persona",
        "human_verdict",
        "reviewer",
        "notes",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for case in sample:
            row = {column: case.model_dump().get(column, "") for column in columns[:8]}
            row.update({"human_verdict": "", "reviewer": "", "notes": ""})
            writer.writerow(row)
    (out_dir / "audit_sample.json").write_text(
        json.dumps([c.model_dump() for c in sample], indent=2), encoding="utf-8"
    )
    return csv_path


def audit_acceptance(audit_csv: str | Path) -> dict[str, Any]:
    """Summarize a *filled* audit sample: agreement rate by category."""
    with Path(audit_csv).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    reviewed = [row for row in rows if row.get("human_verdict")]
    if not reviewed:
        return {"reviewed": 0, "agreement_rate": 0.0, "by_category": {}}
    by_category: dict[str, list[int]] = {}
    for row in reviewed:
        agreed = int(row["human_verdict"] == "agree")
        by_category.setdefault(row["category"], []).append(agreed)
    return {
        "reviewed": len(reviewed),
        "agreement_rate": sum(int(r["human_verdict"] == "agree") for r in reviewed) / len(reviewed),
        "by_category": {category: round(sum(v) / len(v), 4) for category, v in by_category.items()},
    }
