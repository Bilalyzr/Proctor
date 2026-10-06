"""Human sign-off records (GOV-1).

AI evaluators never sign off a release: the record embeds the threshold-file
digest and the run-verdict digest, and a human supplies approver + decision.
``make gate --release`` refuses to pass without a matching record.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from framework.artifacts import sha256_file

# Only these decision values open the release gate (case-insensitive).
APPROVAL_DECISIONS = {"approved", "go", "approved-with-conditions"}

TEMPLATE = """# Release Sign-off Record (GOV-1)

- **When**: {when}
- **Risk tier**: {tier}
- **Thresholds file**: `{thresholds_path}` (sha256 `{thresholds_digest}`)
- **Gate verdict**: `{verdict_path}` (sha256 `{verdict_digest}`)
- **Gate result**: {gate_passed}

## Human decision (required - AI evaluators cannot sign off)

- **Approver (name, role)**: {approver}
- **Decision**: {decision}
- **Notes / conditions**: {notes}

By signing, the approver confirms they reviewed the gate verdict, the run
dashboard and any open findings, and that thresholds reflect the current risk
tier. This record is evidence for GOV-1, not proof of compliance (SOC 2
Type 2 audits controls over time; see SEC-5).
"""


def render_signoff(
    *,
    tier: str,
    thresholds_path: str | Path,
    verdict_path: str | Path,
    gate_passed: bool,
    approver: str,
    decision: str,
    notes: str = "",
    out_path: str | Path = "reports/signoffs/latest.md",
) -> Path:
    """Write a filled sign-off record; the human fields must be non-empty."""
    approver = approver.strip()
    decision = decision.strip()
    if not approver or not decision:
        msg = "GOV-1: approver and decision are required - AI cannot sign off"
        raise ValueError(msg)
    content = TEMPLATE.format(
        when=time.strftime("%Y-%m-%d %H:%M:%S %z"),
        tier=tier,
        thresholds_path=thresholds_path,
        thresholds_digest=sha256_file(thresholds_path),
        verdict_path=verdict_path,
        verdict_digest=sha256_file(verdict_path),
        gate_passed=gate_passed,
        approver=approver,
        decision=decision,
        notes=notes or "-",
    )
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def verify_signoff(
    signoff_path: str | Path,
    *,
    thresholds_path: str | Path,
    verdict_path: str | Path,
) -> bool:
    """True when the record matches the current thresholds and verdict files."""
    path = Path(signoff_path)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if sha256_file(thresholds_path) not in text:
        return False
    if sha256_file(verdict_path) not in text:
        return False
    # Decision must be an explicit human approval (GOV-1: an AI evaluator or
    # a rejected/deferred decision must never open the release gate).
    decision_match = re.search(r"- \*\*Decision\*\*:\s*(.+?)\s*$", text, re.MULTILINE)
    if decision_match is None:
        return False
    decision = decision_match.group(1).strip().strip("`").lower()
    if decision not in APPROVAL_DECISIONS:
        return False
    approver_match = re.search(r"- \*\*Approver \(name, role\)\*\*:\s*(\S.*)", text)
    return approver_match is not None and bool(approver_match.group(1).strip())


def verdict_passed(verdict_path: str | Path) -> bool:
    """Read a gate-verdict JSON and return its overall pass state."""
    data = json.loads(Path(verdict_path).read_text(encoding="utf-8"))
    return bool(data.get("passed"))
