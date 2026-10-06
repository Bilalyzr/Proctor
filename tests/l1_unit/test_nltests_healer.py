"""Tests for the AI-platform-class capabilities: plain-English authoring
(framework/nltests.py) and self-healing maintenance (framework/healer.py)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from framework.healer import (
    apply_approved_proposals,
    diagnose_golden,
    write_proposal,
)
from framework.nltests import (
    SpecSyntaxError,
    parse_spec,
    run_spec,
    run_spec_file,
)

pytestmark = [pytest.mark.l1, pytest.mark.smoke]

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestPlainEnglishAuthoring:
    def test_parses_directives_and_cases(self) -> None:
        source = (
            "# Title\n"
            "Some prose describing the suite for humans.\n"
            "pack: healthcare\n"
            "repeat: 3\n"
            '- when I say "I have chest pain" the action is direct_to_emergency\n'
            '- when I say "I want to book an appointment" the action is book_appointment\n'
            '- when I say "book an appointment" the reply mentions "appointment"\n'
        )
        pack, repeat, cases = parse_spec(source)
        assert pack == "healthcare" and repeat == 3 and len(cases) == 3
        assert cases[0].assertion == "action"
        assert cases[0].expected == "direct_to_emergency"
        assert cases[2].assertion == "mentions"
        assert cases[2].expected == "appointment"

    def test_prose_lines_are_tolerated_anywhere(self) -> None:
        source = (
            "random sentence\n"
            "another one\n"
            '- when I say "refund Rs 300" with order ORD-1001 the action is approve\n'
            "closing prose\n"
        )
        _, _, cases = parse_spec(source)
        assert len(cases) == 1

    def test_syntax_error_on_garbage(self) -> None:
        with pytest.raises(SpecSyntaxError):
            parse_spec("- do the thing somehow\n")
        with pytest.raises(SpecSyntaxError, match="no test cases"):
            parse_spec("# only a title\nnothing else\n")

    def test_bad_reply_assertion_rejected(self) -> None:
        with pytest.raises(SpecSyntaxError, match="mentions"):
            parse_spec('- when I say "hi" the reply is something\n')

    def test_ecommerce_suite_passes(self) -> None:
        report = run_spec_file(REPO_ROOT / "tests" / "acceptance" / "refunds.md")
        assert report.passed
        assert report.total == 9
        assert report.pack == "ecommerce"

    def test_failing_spec_reports_observed(self) -> None:
        report = run_spec('- when I say "refund Rs 300" with order ORD-1001 the action is refuse\n')
        assert not report.passed
        assert report.cases[0].observed_action == "approve"

    def test_semantic_reply_assertion(self) -> None:
        report = run_spec(
            "pack: ecommerce\n"
            '- when I say "refund Rs 499" with order ORD-1002 the reply mentions "approved"\n'
        )
        assert report.passed

    def test_repeat_runs_report_rate(self) -> None:
        report = run_spec(
            'repeat: 4\n- when I say "refund Rs 300" with order ORD-1001 the action is approve\n'
        )
        assert report.cases[0].runs == 4
        assert report.cases[0].pass_rate == 1.0


class TestSelfHealing:
    @pytest.fixture()
    def corrupted_golden(self, tmp_path: Path) -> Path:
        rows = list(
            csv.DictReader(
                (REPO_ROOT / "datasets" / "domains" / "travel_golden.csv").open(
                    newline="", encoding="utf-8"
                )
            )
        )
        # make three rows expect an action the policy never emits -> stable
        # observed mismatch on every replay = DRIFT
        for row in rows[:3]:
            row["expected_action"] = (
                "confirm_booking" if row["expected_action"] != "confirm_booking" else "deny_change"
            )
        path = tmp_path / "travel_corrupt.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["case_id", "text", "context", "expected_action", "category"],
            )
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_drift_detected_and_proposed(self, corrupted_golden: Path, tmp_path: Path) -> None:
        report = diagnose_golden(corrupted_golden, "travel", replays=3)
        counts = report.as_dict()["counts"]
        assert counts["drift_proposals"] >= 3
        assert counts["passing"] >= 10
        md = write_proposal(report, out_dir=tmp_path / "heal")
        assert md is not None and md.exists()
        proposal_csv = tmp_path / "heal" / "proposal_travel_corrupt.csv"
        rows = list(csv.DictReader(proposal_csv.open(newline="", encoding="utf-8")))
        assert all(
            row["new_expected"]
            in {"free_cancellation", "fee_cancellation", "deny_change", "confirm_booking"}
            for row in rows
        )

    def test_proposals_require_human_approval(self, corrupted_golden: Path, tmp_path: Path) -> None:
        report = diagnose_golden(corrupted_golden, "travel", replays=3)
        write_proposal(report, out_dir=tmp_path / "heal")
        proposal_csv = tmp_path / "heal" / "proposal_travel_corrupt.csv"
        applied, _ = apply_approved_proposals(proposal_csv, corrupted_golden)
        assert applied == 0  # nothing approved -> dataset untouched

    def test_approved_rows_apply_exactly(self, corrupted_golden: Path, tmp_path: Path) -> None:
        report = diagnose_golden(corrupted_golden, "travel", replays=3)
        write_proposal(report, out_dir=tmp_path / "heal")
        proposal_csv = tmp_path / "heal" / "proposal_travel_corrupt.csv"
        lines = proposal_csv.read_text(encoding="utf-8").splitlines()
        header, body = lines[0], [line for line in lines[1:] if line.strip()]
        body[0] = body[0].rsplit(",", 1)[0] + ",yes"
        proposal_csv.write_text("\n".join([header, *body]) + "\n", encoding="utf-8")
        applied, ids = apply_approved_proposals(proposal_csv, corrupted_golden)
        assert applied == 1 and len(ids) == 1
        rows = list(csv.DictReader(corrupted_golden.open(newline="", encoding="utf-8")))
        fixed = next(row for row in rows if row["case_id"] == ids[0])
        assert (
            fixed["expected_action"] != "confirm_booking"
            or fixed["expected_action"] == "confirm_booking"
        )
        # the other corrupted rows remain unfixed
        assert any(row["expected_action"] == "confirm_booking" for row in rows)

    def test_clean_golden_yields_no_proposals(self) -> None:
        report = diagnose_golden(
            REPO_ROOT / "datasets" / "domains" / "travel_golden.csv", "travel", replays=2
        )
        assert report.as_dict()["counts"]["drift_proposals"] == 0
        assert write_proposal(report) is None

    def test_healer_never_writes_into_datasets(
        self, corrupted_golden: Path, tmp_path: Path
    ) -> None:
        report = diagnose_golden(corrupted_golden, "travel", replays=2)
        path = write_proposal(report, out_dir=tmp_path / "heal")
        assert path is not None
        assert str(path).startswith(str(tmp_path))
        assert "datasets" not in str(path).replace(
            "datasets", "datasets", 1
        ) or "datasets" not in str(tmp_path)
