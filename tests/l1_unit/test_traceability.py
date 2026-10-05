"""Rank-1 unit tests: executable requirements traceability.

Parses ``docs/traceability.md`` and enforces, on every run:
1. every one of the 31 registry requirements appears exactly once;
2. no unknown requirement IDs sneak in;
3. every row marked ``satisfied`` points at Implementation and Tests paths that
   exist on disk;
4. every requirement whose phase has already been built IS marked satisfied
   (``CURRENT_PHASE`` is bumped each build phase - this test is the ratchet).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from framework.requirements import REQUIREMENT_IDS, REQUIREMENTS, requirement_by_id

pytestmark = [pytest.mark.l1, pytest.mark.smoke]

CURRENT_PHASE = 6  # bump at the end of each build phase

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACEABILITY = REPO_ROOT / "docs" / "traceability.md"
ROW_RE = re.compile(r"^\|\s*(GOV|AST|EVL|RAG|AGT|MCP|SEC|PRD)-\d+\s*\|")
ID_RE = re.compile(r"(GOV|AST|EVL|RAG|AGT|MCP|SEC|PRD)-\d+")
PATH_RE = re.compile(r"`([^`]+)`")


def parse_rows() -> dict[str, dict[str, str]]:
    assert TRACEABILITY.exists(), f"missing {TRACEABILITY}"
    rows: dict[str, dict[str, str]] = {}
    for line in TRACEABILITY.read_text(encoding="utf-8").splitlines():
        if not ROW_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 6, f"row must have 6 cells: {line!r}"
        req_id, _summary, phase, status, impl, tests = cells
        assert req_id not in rows, f"duplicate row for {req_id}"
        rows[req_id] = {"phase": phase, "status": status, "impl": impl, "tests": tests}
    return rows


def test_all_31_requirements_present_exactly_once() -> None:
    rows = parse_rows()
    assert set(rows) == set(REQUIREMENT_IDS)
    assert len(rows) == len(REQUIREMENTS) == 31


def test_registry_phases_match_documented_phases() -> None:
    rows = parse_rows()
    for req in REQUIREMENTS:
        documented = rows[req.id]["phase"]
        assert documented == str(req.phase), (
            f"{req.id}: docs say phase {documented}, registry says {req.phase}"
        )


def test_satisfied_rows_point_at_existing_paths() -> None:
    rows = parse_rows()
    for req_id, row in rows.items():
        if row["status"] != "satisfied":
            continue
        for column in ("impl", "tests"):
            paths = PATH_RE.findall(row[column])
            assert paths, f"{req_id} is satisfied but {column} lists no paths"
            for relative in paths:
                target = REPO_ROOT / relative
                assert target.exists(), f"{req_id}: {relative} does not exist"


def test_phase_ratchet_no_backlog() -> None:
    """Everything due by CURRENT_PHASE must already be satisfied."""
    rows = parse_rows()
    for req in REQUIREMENTS:
        if req.phase > CURRENT_PHASE:
            continue
        assert rows[req.id]["status"] == "satisfied", (
            f"{req.id} was due in phase {req.phase} but is not satisfied"
        )


def test_status_values_are_valid() -> None:
    for row in parse_rows().values():
        assert row["status"] in {"satisfied", "planned"}


def test_requirement_by_id_lookups() -> None:
    assert requirement_by_id("EVL-5").phase == 1
    with pytest.raises(KeyError):
        requirement_by_id("XXX-9")
