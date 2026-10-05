"""Static HTML evaluation dashboard (GOV-3): published per release.

Renders run logs, gate verdicts, guardrail stats and drift reports into one
self-contained HTML file plus a Grafana-style ``dashboard.json`` panel spec.
Offline-friendly (no server needed); a live Grafana would scrape the same
Prometheus output from ``telemetry.metrics``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from framework.runlog import read_run

DASHBOARD_SPEC: dict[str, Any] = {
    "title": "AI QA Framework - Evaluation Dashboard",
    "refresh": "5m",
    "panels": [
        {
            "id": 1,
            "title": "Pass rate by layer (Wilson CI)",
            "type": "stat",
            "query": "aiqa_pass_rate",
        },
        {
            "id": 2,
            "title": "Guardrail blocks by rule",
            "type": "timeseries",
            "query": "aiqa_guardrail_blocks_total",
        },
        {"id": 3, "title": "Golden-slice accuracy", "type": "gauge", "query": "aiqa_accuracy"},
        {
            "id": 4,
            "title": "RAG context precision",
            "type": "timeseries",
            "query": "aiqa_context_precision",
        },
        {
            "id": 5,
            "title": "p95 latency (ms)",
            "type": "timeseries",
            "query": "aiqa_latency_p95_ms",
        },
        {"id": 6, "title": "Drift status (PSI)", "type": "stat", "query": "aiqa_psi"},
    ],
}

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0f1420; color: #e6e9f0; }}
  h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.05rem; margin-top: 2rem; color: #9fb3d1; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; }}
  th, td {{ text-align: left; padding: .45rem .6rem;
           border-bottom: 1px solid #232c42; }}
  th {{ color: #9fb3d1; font-weight: 600; }}
  .pass {{ color: #4cc38a; }} .fail {{ color: #ff6b6b; }} .warn {{ color: #f5c26b; }}
  code {{ color: #8ab4f8; }}
  footer {{ margin-top: 2rem; color: #6b7690; font-size: .8rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p>Generated {generated} &middot; tier <code>{tier}</code>
&middot; provider <code>{provider}</code></p>

<h2>Pyramid gate verdict</h2>
<table><tr><th>Layer</th><th>Status</th><th>Detail</th></tr>{gate_rows}</table>

<h2>Recent runs</h2>
<table><tr><th>Run</th><th>Suite</th><th>Pass</th><th>Fail</th><th>Error</th></tr>{run_rows}</table>

<h2>Guardrails</h2>
<p>{guardrail_summary}</p>

<h2>Drift (PSI)</h2>
<table><tr><th>Metric</th><th>PSI</th><th>Status</th></tr>{drift_rows}</table>

<footer>Evidence for GOV-3. Accuracy figures under the MOCK provider validate
the harness; real-model numbers require provider API keys.</footer>
</body></html>
"""


def render_dashboard(
    *,
    gate_verdict: dict[str, Any] | None = None,
    run_paths: list[Path] | None = None,
    guardrail_stats: dict[str, Any] | None = None,
    drift_reports: list[dict[str, Any]] | None = None,
    tier: str = "critical",
    provider: str = "mock",
    title: str = "AI QA Framework - Evaluation Dashboard",
) -> str:
    """Render the self-contained dashboard HTML."""
    gate_rows = ""
    for result in (gate_verdict or {}).get("results", []):
        css = (
            "pass"
            if result["status"] == "pass"
            else ("fail" if result["status"] == "fail" else "warn")
        )
        detail = ""
        if result.get("details", {}).get("branch_coverage") is not None:
            detail = f"branch coverage {result['details']['branch_coverage']}%"
        gate_rows += (
            f"<tr><td>{result['layer']}</td>"
            f"<td class='{css}'>{result['status']}</td><td>{detail}</td></tr>"
        )
    run_rows = ""
    for path in run_paths or []:
        try:
            records = read_run(path)
        except OSError:
            continue
        footer = next((r for r in records if r["type"] == "run_end"), None)
        if footer is None:
            continue
        run_rows += (
            f"<tr><td><code>{footer['run_id']}</code></td><td>{footer['suite']}</td>"
            f"<td class='pass'>{footer.get('pass_count', 0)}</td>"
            f"<td class='fail'>{footer.get('fail_count', 0)}</td>"
            f"<td class='warn'>{footer.get('error_count', 0)}</td></tr>"
        )
    drift_rows = "".join(
        f"<tr><td>{report['metric']}</td><td>{report['psi']}</td>"
        f"<td class='{'pass' if report['status'] == 'stable' else 'warn'}'>"
        f"{report['status']}</td></tr>"
        for report in drift_reports or []
    )
    guardrail_summary = json.dumps(guardrail_stats or {"status": "no guardrail data"})
    import time as _time

    return _HTML_TEMPLATE.format(
        title=title,
        generated=_time.strftime("%Y-%m-%d %H:%M:%S"),
        tier=tier,
        provider=provider,
        gate_rows=gate_rows or "<tr><td colspan=3>no gate verdict</td></tr>",
        run_rows=run_rows or "<tr><td colspan=5>no runs</td></tr>",
        guardrail_summary=guardrail_summary,
        drift_rows=drift_rows or "<tr><td colspan=3>no drift data</td></tr>",
    )


def publish(
    out_dir: str | Path = "reports/dashboard",
    **kwargs: Any,
) -> list[Path]:
    """Write dashboard.html + dashboard.json (Grafana-style panel spec)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "dashboard.html"
    html_path.write_text(render_dashboard(**kwargs), encoding="utf-8")
    spec_path = out_dir / "dashboard.json"
    spec_path.write_text(json.dumps(DASHBOARD_SPEC, indent=2), encoding="utf-8")
    return [html_path, spec_path]
