"""Domain pack registry + matrix runner.

``python -m domains.matrix`` runs every pack's golden set through the generic
domain agent and prints the pass matrix - one command that proves the harness
tests any vertical, not just finance.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

from domains.base import DomainPack
from domains.criticalops import build_criticalops_pack
from domains.ecommerce import build_ecommerce_pack
from domains.education import build_education_pack
from domains.healthcare import build_healthcare_pack
from domains.runtime import DomainAgent
from framework.statistics import pass_rate_stats

REPO_ROOT = Path(__file__).resolve().parents[1]

_PACKS: dict[str, Any] = {}


def list_packs() -> list[DomainPack]:
    """All registered domain packs (build-once cache)."""
    if not _PACKS:
        for builder in (
            build_ecommerce_pack,
            build_healthcare_pack,
            build_education_pack,
            build_criticalops_pack,
        ):
            pack = builder()
            _PACKS[pack.id] = pack
    return list(_PACKS.values())


def get_pack(pack_id: str) -> DomainPack:
    packs = {pack.id: pack for pack in list_packs()}
    if pack_id not in packs:
        raise KeyError(f"unknown domain pack {pack_id!r}; known: {sorted(packs)}")
    return packs[pack_id]


def load_pack_golden(pack: DomainPack) -> list[dict[str, str]]:
    assert pack.golden_csv is not None and pack.golden_csv.exists(), pack.id
    with pack.golden_csv.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run_pack_matrix() -> dict[str, Any]:
    """Run every pack's golden set through its DomainAgent; report pass rates."""
    matrix: dict[str, Any] = {"packs": {}, "provider": "mock (offline)"}
    for pack in list_packs():
        agent = DomainAgent(pack)
        cases = load_pack_golden(pack)
        correct = 0
        failures: list[str] = []
        for case in cases:
            context: dict[str, Any] = {
                key: _coerce(value)
                for key, value in case.items()
                if key not in {"case_id", "text", "context", "expected_action", "category"}
                and value not in {None, ""}
            }
            if case.get("context"):
                for pair in case["context"].split(";"):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        context[key.strip()] = _coerce(value.strip())
            turn = agent.handle(case["text"], context)
            if turn.action == case["expected_action"]:
                correct += 1
            else:
                failures.append(
                    f"{case['case_id']}: {case['text']!r} -> {turn.action}"
                    f" (want {case['expected_action']})"
                )
        stats = pass_rate_stats(correct, len(cases))
        matrix["packs"][pack.id] = {
            "display_name": pack.display_name,
            "cases": len(cases),
            "passed": correct,
            "pass_rate": round(stats.rate, 4),
            "ci_low": round(stats.ci_low, 4),
            "failures": failures,
            "risk_note": pack.risk_note,
        }
    matrix["all_green"] = all(entry["pass_rate"] >= 0.90 for entry in matrix["packs"].values())
    return matrix


def _coerce(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.isdigit():
        return int(value)
    return value


def main(argv: list[str] | None = None) -> int:
    matrix = run_pack_matrix()
    out = REPO_ROOT / "reports" / "domain_matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    for pack_id, entry in matrix["packs"].items():
        status = "GREEN" if entry["pass_rate"] >= 0.90 else "RED"
        print(
            f"[matrix] {pack_id:<13} {status} {entry['passed']}/{entry['cases']}"
            f" (rate {entry['pass_rate']}, CI low {entry['ci_low']}) - {entry['display_name']}"
        )
        for failure in entry["failures"]:
            print(f"          FAIL {failure}")
    print(f"[matrix] report: {out}")
    return 0 if matrix["all_green"] else 1


if __name__ == "__main__":
    sys.exit(main())
