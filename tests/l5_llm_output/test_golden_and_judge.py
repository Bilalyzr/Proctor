"""Judge calibration (EVL-4) and golden-slice accuracy (blueprint Section 7).

The >90% accuracy target is measured ONLY on the human-verified golden slice;
with the mock provider this validates the measurement harness itself - real
numbers require a real provider, and every report says so.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clients.mock import MockClient
from evals.calibrate import calibrate, load_calibration
from evals.judge import MockJudge
from framework.config import Settings
from framework.statistics import spearman_rho
from sut.agent import RefundAssistant
from synthetic.generator import GeneratedCase

pytestmark = [pytest.mark.l5, pytest.mark.nightly]

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def assistant():
    settings = Settings(_env_file=None)
    return RefundAssistant(
        MockClient(settings.model_name_for("mock"), seed=settings.seed), settings=settings
    )


def load_golden_slice() -> list[dict[str, str]]:
    with (ROOT / "datasets" / "golden" / "refund_golden.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        return list(csv.DictReader(handle))


class TestJudgeCalibration:
    def test_spearman_gate_on_human_labels(self, assistant) -> None:
        """EVL-4: judge-human Spearman rho >= 0.8."""
        rows = load_calibration(ROOT / "datasets" / "golden" / "judge_calibration.csv")
        judge = MockJudge()
        judge_scores: list[float] = []
        human_scores: list[float] = []
        for row in rows:
            case = GeneratedCase(
                case_id="cal",
                text=row.question,
                order_id=row.order_id,
                expected_action=row.expected_action,
                category="calibration",
                intent="calibration",
                persona="reviewer",
            )
            turn = assistant.handle(row.question, order_id=row.order_id)
            judge_scores.append(judge.score(case, turn))
            human_scores.append(row.human_score)
        result = calibrate(judge_scores, human_scores)
        assert result["passed"], f"rho={result['spearman_rho']} below 0.8"
        assert result["n"] >= 20

    def test_spearman_reference_values(self) -> None:
        assert spearman_rho([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)
        assert spearman_rho([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
        with pytest.raises(ValueError):
            spearman_rho([1], [1])
        with pytest.raises(ValueError):
            spearman_rho([1, 2], [1])

    def test_mismatched_inputs_rejected(self) -> None:
        with pytest.raises(ValueError):
            calibrate([1.0, 0.5], [1.0])

    def test_calibration_loader(self, tmp_path) -> None:
        rows = load_calibration(ROOT / "datasets" / "golden" / "judge_calibration.csv")
        assert len(rows) >= 20
        assert all(0.0 <= r.human_score <= 1.0 for r in rows)
        tiny = tmp_path / "tiny.csv"
        tiny.write_text(
            "question,order_id,expected_action,human_score\nrefund ₹1,ORD-1,approve,1.0\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="too small"):
            load_calibration(tiny)


class TestGoldenSliceAccuracy:
    def test_accuracy_on_human_verified_slice(self, assistant) -> None:
        """The accuracy metric that matters: golden slice, not synthetic bulk."""
        cases = load_golden_slice()
        correct = 0
        failures: list[str] = []
        for case in cases:
            turn = assistant.handle(case["text"], order_id=case["order_id"] or None)
            if turn.decision.action.value == case["expected_action"]:
                correct += 1
            else:
                failures.append(
                    f"{case['case_id']}: {case['text']!r} -> {turn.decision.action.value}"
                    f" (want {case['expected_action']})"
                )
        accuracy = correct / len(cases)
        assert accuracy > 0.90, f"golden-slice accuracy {accuracy:.3f}: {failures}"
        # and the zero-breach invariant holds on the slice too
        for case in cases:
            turn = assistant.handle(case["text"], order_id=case["order_id"] or None)
            if turn.decision.action.value == "approve":
                assert (turn.decision.amount_paise or 0) <= 50_000

    def test_slice_covers_the_risk_categories(self) -> None:
        categories = {case["category"] for case in load_golden_slice()}
        assert {"boundary", "currency", "injection", "negative", "split"} <= categories

    def test_mock_provider_disclaimer_is_honest(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.provider == "mock"  # these numbers are harness validation
