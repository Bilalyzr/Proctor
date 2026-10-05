"""Rank-1 unit tests for Phase-6 infrastructure: telemetry (PRD-2), the
feedback-to-test pipeline (PRD-3), and differential evaluation (GOV-5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.diff_eval import run_differential, write_diff_report
from framework.feedback import load_feedback, promote_to_regression, run_feedback_cycle, triage
from telemetry.dashboard import DASHBOARD_SPEC, publish, render_dashboard
from telemetry.drift import psi, psi_report
from telemetry.metrics import MetricsRegistry

pytestmark = [pytest.mark.l1, pytest.mark.smoke]

REPO_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------- telemetry
class TestMetrics:
    def test_counters_and_prometheus_render(self) -> None:
        metrics = MetricsRegistry()
        metrics.record_counter("guardrail_blocks_total", rule="injection:x")
        metrics.record_counter("guardrail_blocks_total", 2, rule="dlp:email")
        metrics.record_gauge("accuracy", 0.93, provider="mock")
        rendered = metrics.render_prometheus()
        assert 'aiqa_guardrail_blocks_total{rule="dlp:email"} 2' in rendered
        assert 'aiqa_accuracy{provider="mock"} 0.93' in rendered
        assert "# TYPE aiqa_guardrail_blocks_total counter" in rendered
        snapshot = metrics.snapshot()
        assert len(snapshot["counters"]) == 2 and len(snapshot["gauges"]) == 1


class TestDrift:
    def test_psi_identical_samples_stable(self) -> None:
        sample = [float(i) for i in range(1, 101)]
        report = psi_report("accuracy", sample, list(sample))
        assert report.psi == pytest.approx(0.0, abs=1e-9)
        assert report.status == "stable"

    def test_psi_shifted_sample_alerts(self) -> None:
        reference = [float(i) for i in range(1, 101)]
        shifted = [value + 50 for value in reference]
        report = psi_report("context_precision", reference, shifted)
        assert report.status in ("investigate", "alert")
        assert report.psi > 0.1

    def test_psi_small_uniform_shift_stays_stable(self) -> None:
        """A 5% uniform scale shift is within noise for PSI - by design."""
        reference = [float(i) for i in range(1, 1001)]
        shifted = [value * 1.05 for value in reference]
        report = psi_report("latency", reference, shifted)
        assert report.psi < 0.1
        assert report.status == "stable"

    def test_psi_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            psi([], [1.0, 2.0])


class TestDashboard:
    def test_spec_has_core_panels(self) -> None:
        titles = " ".join(panel["title"] for panel in DASHBOARD_SPEC["panels"])
        for phrase in ("Pass rate", "Guardrail", "accuracy", "latency", "Drift"):
            assert phrase.lower() in titles.lower()

    def test_render_and_publish(self, tmp_path: Path) -> None:
        verdict = {
            "results": [
                {"layer": "l1", "status": "pass", "details": {"branch_coverage": 89.2}},
                {"layer": "l2", "status": "fail", "details": {}},
            ]
        }
        html = render_dashboard(
            gate_verdict=verdict,
            guardrail_stats={"blocked": 3},
            drift_reports=[{"metric": "accuracy", "psi": 0.31, "status": "alert"}],
        )
        assert "l1" in html and "89.2" in html and "alert" in html
        paths = publish(out_dir=tmp_path / "dash", gate_verdict=verdict)
        assert (tmp_path / "dash" / "dashboard.html").exists()
        spec = json.loads((tmp_path / "dash" / "dashboard.json").read_text(encoding="utf-8"))
        assert spec["panels"]
        assert len(paths) == 2


# ------------------------------------------------------------------- feedback
class TestFeedbackPipeline:
    def test_load_and_triage(self) -> None:
        rows = load_feedback(REPO_ROOT / "datasets" / "feedback" / "feedback.csv")
        assert len(rows) >= 6
        summary = triage(rows)
        assert summary["thumbs_down"] >= 3
        assert summary["retries"] >= 3
        assert summary["clusters"]

    def test_promotion_creates_regression_rows(self, tmp_path: Path) -> None:
        rows = load_feedback(REPO_ROOT / "datasets" / "feedback" / "feedback.csv")
        promoted = promote_to_regression(rows, tmp_path / "from_feedback.csv")
        assert promoted
        assert {row["category"] for row in promoted} == {"from_feedback"}
        for row in promoted:
            assert row["expected_action"] in {"approve", "refuse", "ask_info"}
        # rerun: dedup against the file just written
        again = promote_to_regression(rows, tmp_path / "from_feedback.csv")
        assert again == []

    def test_full_cycle_writes_log(self, tmp_path: Path) -> None:
        log = run_feedback_cycle(
            REPO_ROOT / "datasets" / "feedback" / "feedback.csv",
            tmp_path / "golden.csv",
            log_path=tmp_path / "cycle.json",
        )
        assert log["cycle_at"]
        assert log["promoted_cases"]
        assert (tmp_path / "cycle.json").exists()
        payload = json.loads((tmp_path / "cycle.json").read_text(encoding="utf-8"))
        assert payload["thumbs_down"] >= 3


# ------------------------------------------------------------- differential eval
class TestDifferentialEval:
    def test_go_when_equivalent(self) -> None:
        report = run_differential(
            REPO_ROOT / "datasets" / "golden" / "refund_golden.csv",
            config_a={"seed": 42},
            config_b={"seed": 43},
        )
        assert report.decision == "go"
        assert report.accuracy_a > 0.9 and report.accuracy_b > 0.9

    def test_report_written(self, tmp_path: Path) -> None:
        report = run_differential(
            REPO_ROOT / "datasets" / "golden" / "refund_golden.csv",
            config_a={"seed": 1},
            config_b={"seed": 2},
            label_a="gemini-2.0",
            label_b="gemini-2.1",
        )
        path = write_diff_report(report, tmp_path / "diff.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["decision"] == "go"
        assert payload["label_a"] == "gemini-2.0"
        assert (
            payload["by_category_a"]["boundary"]
            >= payload["by_category_b"].get("boundary", 0) - 0.0
        )
