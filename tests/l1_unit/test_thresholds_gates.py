"""Rank-1 unit tests: threshold files, gate runner, sign-off records (GOV-1/2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.gates import (
    IMPLEMENTED_LAYERS,
    GateVerdict,
    LayerResult,
    check_layer,
    run_gates,
    write_verdict,
)
from framework.signoff import render_signoff, verdict_passed, verify_signoff
from framework.thresholds import ThresholdFile, available_tiers, load_thresholds

pytestmark = pytest.mark.l1

REPO_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ thresholds
class TestThresholds:
    def test_all_tiers_load_and_validate(self) -> None:
        for tier in ("critical", "high", "standard"):
            thresholds = load_thresholds(tier, REPO_ROOT / "thresholds")
            assert thresholds.tier == tier
            assert "l1" in thresholds.layers and "l2" in thresholds.layers

    def test_critical_matches_blueprint_defaults(self) -> None:
        critical = load_thresholds("critical", REPO_ROOT / "thresholds")
        assert critical.gate_value("l1", "min_branch_coverage") == 0.85
        assert critical.gate_value("l2", "min_pass_rate") == 0.95
        assert critical.gate_value("l2", "max_policy_breaches") == 0
        assert critical.gate_value("l4", "min_recall_at_5") == 0.90
        assert critical.gate_value("l6", "min_faithfulness") == 0.90
        assert critical.gate_value("l7", "min_tool_call_accuracy") == 0.95

    def test_gate_value_missing_key_raises(self) -> None:
        thresholds = ThresholdFile(version=1, tier="critical", layers={"l1": {}})
        with pytest.raises(KeyError):
            thresholds.gate_value("l1", "min_branch_coverage")
        assert thresholds.gate_value("l1", "min_branch_coverage", default=0.5) == 0.5

    @pytest.mark.parametrize(
        ("payload", "match"),
        [
            ({"version": 1, "tier": "extreme", "layers": {}}, "unknown tier"),
            ({"version": 1, "tier": "critical", "layers": {"l0": {}}}, "unknown layers"),
        ],
    )
    def test_invalid_files_rejected(self, payload: dict, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            ThresholdFile.model_validate(payload)

    def test_unknown_tier_rejected_by_loader(self) -> None:
        with pytest.raises(ValueError):
            load_thresholds("extreme", REPO_ROOT / "thresholds")

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_thresholds("critical", REPO_ROOT / "nowhere")

    def test_available_tiers(self) -> None:
        assert available_tiers(REPO_ROOT / "thresholds") == ["critical", "high", "standard"]


# ------------------------------------------------------------------ gate runner
def ok_executor(command) -> int:
    return 0


def fail_l1_executor(command) -> int:
    return 1 if "--cov-report=json" in command else 0  # the L1 coverage step


class TestGateRunner:
    def test_climb_stops_at_first_failure(self, tmp_path: Path) -> None:
        thresholds = load_thresholds("critical", REPO_ROOT / "thresholds")
        verdict = run_gates(
            thresholds, executor=fail_l1_executor, coverage_json=tmp_path / "c.json"
        )
        statuses = {r.layer: r.status for r in verdict.results}
        assert statuses["l1"] == "fail"
        assert "l2" not in statuses  # never ran - lower layer failed
        assert verdict.passed is False
        assert verdict.stopped_at == "l1"

    def test_unbuilt_layers_noted_climb_continues(self, tmp_path: Path) -> None:
        coverage = tmp_path / "coverage.json"
        coverage.write_text(json.dumps({"totals": {"percent_covered": 95.0}}), encoding="utf-8")
        thresholds = load_thresholds("critical", REPO_ROOT / "thresholds")
        verdict = run_gates(thresholds, executor=ok_executor, coverage_json=coverage)
        statuses = {r.layer: r.status for r in verdict.results}
        assert statuses["l1"] == "pass" and statuses["l2"] == "pass"
        all_layers = ("l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9")
        unbuilt = [layer for layer in all_layers if layer not in IMPLEMENTED_LAYERS]
        built = [layer for layer in all_layers if layer in IMPLEMENTED_LAYERS]
        assert all(statuses[layer] == "not_built" for layer in unbuilt)
        assert all(statuses[layer] == "pass" for layer in built)  # climb continued past gaps
        assert verdict.passed is True
        assert verdict.stopped_at == "complete"

    def test_l1_coverage_below_threshold_fails(self, tmp_path: Path) -> None:
        coverage = tmp_path / "coverage.json"
        coverage.write_text(json.dumps({"totals": {"percent_covered": 70.0}}), encoding="utf-8")
        thresholds = load_thresholds("critical", REPO_ROOT / "thresholds")
        result = check_layer("l1", thresholds, executor=ok_executor, coverage_json=coverage)
        assert result.status == "fail"
        assert result.details["branch_coverage"] == 70.0

    def test_l1_coverage_at_threshold_passes(self, tmp_path: Path) -> None:
        coverage = tmp_path / "coverage.json"
        coverage.write_text(json.dumps({"totals": {"percent_covered": 85.2}}), encoding="utf-8")
        thresholds = load_thresholds("critical", REPO_ROOT / "thresholds")
        result = check_layer("l1", thresholds, executor=ok_executor, coverage_json=coverage)
        assert result.status == "pass"

    def test_coverage_file_unreadable_fails(self, tmp_path: Path) -> None:
        thresholds = load_thresholds("critical", REPO_ROOT / "thresholds")
        result = check_layer(
            "l1", thresholds, executor=ok_executor, coverage_json=tmp_path / "missing.json"
        )
        assert result.status == "fail"
        assert "coverage unreadable" in result.details["error"]

    def test_verdict_written_to_disk(self, tmp_path: Path) -> None:
        verdict = GateVerdict(
            passed=True,
            stopped_at="l3",
            results=[LayerResult("l1", "pass", 0.1, {}), LayerResult("l3", "not_built")],
        )
        path = write_verdict(verdict, tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["passed"] is True
        assert payload["results"][0]["layer"] == "l1"
        assert (tmp_path / "latest_gate_verdict.json").exists()


# ---------------------------------------------------------------------- signoff
class TestSignoff:
    def _verdict(self, tmp_path: Path) -> Path:
        return write_verdict(
            GateVerdict(passed=True, stopped_at="l3", results=[LayerResult("l1", "pass")]),
            tmp_path,
        )

    def test_render_and_verify_roundtrip(self, tmp_path: Path) -> None:
        verdict_path = self._verdict(tmp_path)
        record = render_signoff(
            tier="critical",
            thresholds_path=REPO_ROOT / "thresholds" / "critical.yaml",
            verdict_path=verdict_path,
            gate_passed=True,
            approver="Meera QA-Lead",
            decision="approved",
            out_path=tmp_path / "signoffs" / "latest.md",
        )
        assert verify_signoff(
            record,
            thresholds_path=REPO_ROOT / "thresholds" / "critical.yaml",
            verdict_path=verdict_path,
        )

    def test_missing_human_fields_rejected(self, tmp_path: Path) -> None:
        verdict_path = self._verdict(tmp_path)
        with pytest.raises(ValueError, match="AI cannot sign off"):
            render_signoff(
                tier="critical",
                thresholds_path=REPO_ROOT / "thresholds" / "critical.yaml",
                verdict_path=verdict_path,
                gate_passed=True,
                approver="  ",
                decision="approved",
            )

    def test_stale_signoff_fails_verification(self, tmp_path: Path) -> None:
        verdict_path = self._verdict(tmp_path)
        record = render_signoff(
            tier="critical",
            thresholds_path=REPO_ROOT / "thresholds" / "critical.yaml",
            verdict_path=verdict_path,
            gate_passed=True,
            approver="Rahul PO",
            decision="approved",
            out_path=tmp_path / "s.md",
        )
        # thresholds changed after sign-off -> digest mismatch -> invalid
        other = tmp_path / "other.yaml"
        other.write_text("version: 99\ntier: critical\nlayers: {}\n", encoding="utf-8")
        assert not verify_signoff(record, thresholds_path=other, verdict_path=verdict_path)
        assert not verify_signoff(
            tmp_path / "nope.md", thresholds_path=other, verdict_path=verdict_path
        )

    def test_verdict_passed_reader(self, tmp_path: Path) -> None:
        path = self._verdict(tmp_path)
        assert verdict_passed(path) is True
        failing = write_verdict(GateVerdict(passed=False, stopped_at="l2"), tmp_path)
        assert verdict_passed(failing) is False
