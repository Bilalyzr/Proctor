"""Executable integrity check for docs/checklist-coverage.md: every row is
well-formed, statuses are known, and the honest split is visible (nothing
reads `covered` without evidence)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.l1, pytest.mark.smoke]

DOC = Path(__file__).resolve().parents[2] / "docs" / "checklist-coverage.md"
STATUSES = {"covered", "partial", "pending", "not-applicable"}
ROW_RE = re.compile(r"^\|[^|]+|[^|]+|[^|]+|[^|]+\|$")


def parse_rows() -> list[tuple[str, str, str, str]]:
    assert DOC.exists()
    rows: list[tuple[str, str, str, str]] = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= {"|", "-", " "}:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0] in {"Area", "---"} or set(cells[0]) <= {"-"}:
            continue
        assert len(cells) == 4, f"row needs 4 cells: {line!r}"
        rows.append((cells[0], cells[1], cells[2], cells[3]))
    return rows


def test_document_is_wellformed_with_known_statuses() -> None:
    rows = parse_rows()
    assert len(rows) >= 70, f"expected ~70 checklist items, got {len(rows)}"
    for area, item, status, evidence in rows:
        assert area and item, f"empty area/item: {area!r} {item!r}"
        assert status in STATUSES, f"unknown status {status!r} on {item!r}"
        if status == "covered":
            assert evidence and evidence != "—", f"covered item lacks evidence: {item!r}"


def test_all_twelve_areas_present() -> None:
    areas = {area for area, *_ in parse_rows()}
    expected = {
        "Requirement & Risk Analysis",
        "Test Data Management",
        "Model Testing",
        "API & Backend Testing",
        "AI/LLM-Specific Testing",
        "UI/E2E Testing",
        "Performance Testing",
        "Security Testing",
        "Evaluation & Quality Gates",
        "CI/CD & Automation",
        "Production Monitoring",
        "Continuous Improvement",
    }
    assert expected <= areas, f"missing areas: {expected - areas}"


def test_honest_mix_is_present() -> None:
    """The map must keep partial/pending/NA rows visible - a map claiming
    100% coverage everywhere would be dishonest given docs/TODO.md."""
    statuses = {status for _, _, status, _ in parse_rows()}
    assert "covered" in statuses
    assert {"partial", "pending"} & statuses
    counts: dict[str, int] = {}
    for _, _, status, _ in parse_rows():
        counts[status] = counts.get(status, 0) + 1
    covered = counts.get("covered", 0)
    assert covered / len(parse_rows()) >= 0.7, f"coverage collapsed: {counts}"
