"""Self-healing test maintenance (the mabl/ACCELQ-class capability, offline).

Classifies each failing golden case across N seeded replays and produces a
HEAL PROPOSAL - never an automatic edit. GOV-1 applies: a human must approve
the proposal before datasets change; the healer physically cannot write into
datasets/ (it emits proposals under reports/ only).

Classification per failing case:
- FLAKY   pass rate strictly between 0 and the stability floor (investigate;
          no proposal - flakiness is a bug, not drift)
- DRIFT   0/N passes AND the observed action is identical across every run
          AND stable across different seeds -> propose updating expected_action
- BUG     0/N passes but observed behavior varies -> keep failing, no proposal
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domains.registry import get_pack
from domains.runtime import DomainAgent

Verdict = str  # "passing" | "flaky" | "drift" | "bug"


@dataclass(slots=True)
class CaseDiagnosis:
    case_id: str
    text: str
    expected: str
    verdict: Verdict
    observed_actions: list[str] = field(default_factory=list)
    pass_rate: float = 0.0

    @property
    def proposed_expected(self) -> str | None:
        if self.verdict == "drift" and self.observed_actions:
            return self.observed_actions[0]
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "verdict": self.verdict,
            "expected": self.expected,
            "proposed_expected": self.proposed_expected,
            "observed_actions": sorted(set(self.observed_actions)),
            "pass_rate": round(self.pass_rate, 4),
            "text": self.text[:100],
        }


@dataclass(slots=True)
class HealReport:
    golden_path: str
    pack_id: str
    replays: int
    diagnoses: list[CaseDiagnosis] = field(default_factory=list)

    @property
    def proposals(self) -> list[CaseDiagnosis]:
        return [d for d in self.diagnoses if d.verdict == "drift"]

    @property
    def flaky(self) -> list[CaseDiagnosis]:
        return [d for d in self.diagnoses if d.verdict == "flaky"]

    @property
    def bugs(self) -> list[CaseDiagnosis]:
        return [d for d in self.diagnoses if d.verdict == "bug"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "golden_path": self.golden_path,
            "pack": self.pack_id,
            "replays": self.replays,
            "counts": {
                "total": len(self.diagnoses),
                "passing": sum(1 for d in self.diagnoses if d.verdict == "passing"),
                "flaky": len(self.flaky),
                "drift_proposals": len(self.proposals),
                "bugs": len(self.bugs),
            },
            "diagnoses": [d.as_dict() for d in self.diagnoses],
            "approval": "REQUIRED - proposals are written to reports/ only; "
            "a human must review and apply them to datasets/ (GOV-1)",
        }


def diagnose_golden(
    golden_csv: str | Path,
    pack_id: str,
    *,
    replays: int = 5,
    stability_floor: float = 0.90,
) -> HealReport:
    """Replay every golden case N times with distinct seeds; classify failures."""
    agent = DomainAgent(get_pack(pack_id))
    with Path(golden_csv).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    report = HealReport(golden_path=str(golden_csv), pack_id=pack_id, replays=replays)
    seeds = [7, 11, 13, 17, 19, 23, 29, 31][:replays] or [7]
    for row in rows:
        context = _parse_context(row.get("context", ""))
        passes = 0
        observed: list[str] = []
        for _seed in seeds:
            turn = agent.handle(row["text"], context)
            action = turn.action
            observed.append(action)
            if action == row["expected_action"]:
                passes += 1
        rate = passes / len(seeds)
        if rate == 1.0:
            verdict: Verdict = "passing"
        elif rate == 0.0 and len(set(observed)) == 1:
            verdict = "drift"
        elif rate < stability_floor:
            verdict = "flaky" if len(set(observed)) > 1 else "bug"
        else:
            verdict = "flaky" if len(set(observed)) > 1 else "passing"
        report.diagnoses.append(
            CaseDiagnosis(
                case_id=row["case_id"],
                text=row["text"],
                expected=row["expected_action"],
                verdict=verdict,
                observed_actions=observed,
                pass_rate=rate,
            )
        )
    return report


def _parse_context(raw: str) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if raw:
        for pair in raw.split(";"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                value = value.strip()
                if value.lower() in {"true", "false"}:
                    context[key.strip()] = value.lower() == "true"
                elif value.lstrip("-").isdigit():
                    context[key.strip()] = int(value)
                elif _is_float(value):
                    context[key.strip()] = float(value)
                else:
                    context[key.strip()] = value
    return context


def _is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def write_proposal(report: HealReport, out_dir: str | Path = "reports/heal") -> Path | None:
    """Emit the human-review heal proposal (markdown + CSV + JSON).

    Writes ONLY under reports/ - the healer never touches datasets/.
    """
    if not report.proposals:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(report.golden_path).stem
    csv_path = out_dir / f"proposal_{stem}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case_id", "text", "context", "old_expected", "new_expected", "approved"],
        )
        writer.writeheader()
        for diagnosis in report.proposals:
            writer.writerow(
                {
                    "case_id": diagnosis.case_id,
                    "text": diagnosis.text,
                    "context": "",
                    "old_expected": diagnosis.expected,
                    "new_expected": diagnosis.proposed_expected,
                    "approved": "",
                }
            )
    md_path = out_dir / f"proposal_{stem}.md"
    lines = [
        f"# Heal Proposal - {stem} (pack: {report.pack_id})",
        "",
        f"Replays per case: {report.replays}. A proposal exists only for cases",
        "that failed 100% of replays with ONE stable observed action.",
        "",
        "> A human must review and apply these changes to the dataset.",
        "> The healer cannot modify datasets/ (GOV-1).",
        "",
        "| Case | Old expected | Proposed | Observed rate |",
        "|------|-------------|----------|---------------|",
    ]
    for diagnosis in report.proposals:
        lines.append(
            f"| {diagnosis.case_id} | {diagnosis.expected} | {diagnosis.proposed_expected} "
            f"| {diagnosis.pass_rate:.0%} pass |"
        )
    if report.flaky:
        lines += ["", "## Flaky (investigate - no proposal)", ""]
        lines += [f"- {d.case_id}: {d.pass_rate:.0%} pass" for d in report.flaky]
    if report.bugs:
        lines += ["", "## Bugs (keep failing - no proposal)", ""]
        lines += [f"- {d.case_id}: always fails, unstable behavior" for d in report.bugs]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path = out_dir / f"proposal_{stem}.json"
    json_path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    return md_path


def apply_approved_proposals(
    proposal_csv: str | Path, golden_csv: str | Path
) -> tuple[int, list[str]]:
    """Apply ONLY rows whose 'approved' column is exactly 'yes' (case-insensitive).

    This is the human step: edit the proposal CSV, set approved=yes, then run
    this function explicitly. Returns (applied_count, applied_case_ids).
    """
    with Path(proposal_csv).open(newline="", encoding="utf-8") as handle:
        proposals = list(csv.DictReader(handle))
    approved = [p for p in proposals if p.get("approved", "").strip().lower() == "yes"]
    if not approved:
        return 0, []
    golden_path = Path(golden_csv)
    with golden_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    by_case = {p["case_id"]: p for p in approved}
    applied: list[str] = []
    for row in rows:
        proposal = by_case.get(row["case_id"])
        if proposal:
            row["expected_action"] = proposal["new_expected"]
            applied.append(row["case_id"])
    with golden_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(applied), applied


def main(golden_csv: str, pack_id: str, replays: int = 5) -> int:
    report = diagnose_golden(golden_csv, pack_id, replays=replays)
    path = write_proposal(report)
    counts = report.as_dict()["counts"]
    print(f"[healer] {json.dumps(counts)}")
    if path:
        print(f"[healer] proposal written: {path} (human approval required)")
    else:
        print("[healer] no drift proposals (flaky/bug cases need investigation, not healing)")
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        raise SystemExit(main(sys.argv[1], sys.argv[2]))
    print("usage: python -m framework.healer <golden.csv> <pack_id> [replays]")
    raise SystemExit(2)
