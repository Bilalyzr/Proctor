"""SOC 2 Type 2 evidence pack generator (SEC-5).

SOC 2 Type 2 is an *audit of controls over time* performed by an external
auditor. This module generates EVIDENCE - control mappings, run logs, scan
results, threshold digests, sign-off records - and packages them with an
explicit non-claim: nothing here certifies compliance.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from framework.artifacts import sha256_file

# SOC 2 Trust Services criteria (common criteria focus) mapped to framework controls
CONTROL_MATRIX: list[dict[str, str]] = [
    {
        "criterion": "CC1.4 (accountability)",
        "control": "Human sign-off required for release (GOV-1); AI never signs off alone",
        "evidence": "reports/signoffs/latest.md + framework/signoff.py",
    },
    {
        "criterion": "CC2.1 (information criteria)",
        "control": "Thresholds versioned per risk tier and hashed into runs (GOV-2)",
        "evidence": "thresholds/*.yaml digests in run manifests",
    },
    {
        "criterion": "CC2.2 (internal/external communication)",
        "control": "Evaluation dashboards published per release (GOV-3)",
        "evidence": "telemetry/dashboard.py output + nightly artifacts",
    },
    {
        "criterion": "CC3.x / CC4.x (monitoring activities)",
        "control": "Nightly regression on every active branch (GOV-4)",
        "evidence": ".github/workflows/nightly.yml run history",
    },
    {
        "criterion": "CC6.1 (logical access - secrets)",
        "control": "Secret scan of repo and outbound key masking (SEC-2)",
        "evidence": "secret scan results in this pack",
    },
    {
        "criterion": "CC6.6 (external access - ports)",
        "control": "Port/listener posture check: stdio MCP server binds no socket (SEC-2)",
        "evidence": "port scan result in this pack",
    },
    {
        "criterion": "CC6.7 (data in transit)",
        "control": "DLP on RAG context and outputs (SEC-3)",
        "evidence": "guardrail event log",
    },
    {
        "criterion": "CC7.1 (anomaly detection)",
        "control": "Injection guardrail + drift telemetry (SEC-1, PRD-2)",
        "evidence": "guardrail stats + telemetry drift report",
    },
    {
        "criterion": "CC7.2 (incident monitoring)",
        "control": "Circuit breakers stop runaway agents and log trips (AGT-1..4)",
        "evidence": "breaker trip summaries in L7 results",
    },
    {
        "criterion": "CC8.1 (change management)",
        "control": "Differential evaluation before model swaps (GOV-5)",
        "evidence": "framework/diff_eval.py reports",
    },
    {
        "criterion": "CC9.2 (vendor management)",
        "control": "Provider-agnostic client makes supplier swaps testable (GOV-5)",
        "evidence": "adapter contract tests",
    },
]

DISCLAIMER = (
    "This pack is EVIDENCE for a SOC 2 Type 2 audit. SOC 2 Type 2 evaluates "
    "controls over time and is certified by an external auditor, never by this "
    "repository. No compliance is claimed or implied."
)


def build_evidence_pack(
    repo_root: str | Path,
    *,
    secret_scan: dict[str, Any] | None = None,
    port_scan: dict[str, Any] | None = None,
    guardrail_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the evidence pack structure (JSON-serializable)."""
    root = Path(repo_root)
    artifacts: dict[str, str] = {}
    for name, relative in {
        "thresholds_critical": "thresholds/critical.yaml",
        "thresholds_high": "thresholds/high.yaml",
        "prompt": "sut/prompts.py",
        "taxonomy": "datasets/synthetic/taxonomy.yaml",
    }.items():
        path = root / relative
        if path.exists():
            artifacts[name] = sha256_file(path)
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "disclaimer": DISCLAIMER,
        "controls": CONTROL_MATRIX,
        "artifact_digests": artifacts,
        "scans": {
            "secret_scan": secret_scan or {"status": "not-run"},
            "port_scan": port_scan or {"status": "not-run"},
        },
        "guardrail_stats": guardrail_stats or {"status": "not-run"},
    }


def write_evidence_pack(pack: dict[str, Any], out_dir: str | Path) -> list[Path]:
    """Write the pack as markdown + JSON; returns the written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "soc2_evidence.json"
    json_path.write_text(json.dumps(pack, indent=2), encoding="utf-8")

    lines = [
        "# SOC 2 Type 2 Evidence Pack",
        "",
        f"_Generated: {pack['generated_at']}_",
        "",
        f"> {pack['disclaimer']}",
        "",
        "| Criterion | Control | Evidence |",
        "|-----------|---------|----------|",
    ]
    for control in pack["controls"]:
        lines.append(f"| {control['criterion']} | {control['control']} | `{control['evidence']}` |")
    lines += [
        "",
        "## Artifact digests",
        "",
        *(f"- `{name}`: `{digest}`" for name, digest in pack["artifact_digests"].items()),
        "",
        "## Scan results",
        "",
        f"```json\n{json.dumps(pack['scans'], indent=2)}\n```",
        "",
        f"Guardrail stats: `{json.dumps(pack['guardrail_stats'])}`",
    ]
    md_path = out_dir / "soc2_evidence.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return [md_path, json_path]
