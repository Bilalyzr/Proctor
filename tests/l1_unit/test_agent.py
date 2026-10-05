"""Rank-1 unit tests: the refund assistant end to end on the MOCK provider.

Includes the Week-1 exit-gate scenario: one model call, logged end to end with
artifact-linked run metadata (AST-1), and the code-side cap guard catching a
deliberately non-compliant model (blueprint Section 1: zero-breach posture).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clients.base import CompletionRequest, ModelClientError, TransientModelError
from clients.mock import MockClient, MockStep
from framework.artifacts import snapshot
from framework.config import Settings
from framework.runlog import RunLogger, read_run
from sut.agent import RefundAssistant
from sut.schemas import AgentAction

pytestmark = pytest.mark.l1


def make_assistant(
    tmp_path: Path | None = None,
    client: MockClient | None = None,
) -> tuple[RefundAssistant, RunLogger | None]:
    settings = Settings(_env_file=None)
    logger = None
    if tmp_path is not None:
        artifacts = snapshot({"prompts": Path(__file__).resolve().parents[2] / "sut"})
        logger = RunLogger(
            log_dir=tmp_path / "reports",
            suite="agent-e2e",
            params=settings.generation_params(),
            artifacts=artifacts,
        )
        logger.open()
    assistant = RefundAssistant(
        client if client is not None else MockClient(seed=settings.seed),
        settings=settings,
        run_logger=logger,
    )
    return assistant, logger


class TestHappyPaths:
    def test_approve_within_cap_logs_end_to_end(self, tmp_path: Path) -> None:
        assistant, logger = make_assistant(tmp_path)
        assert logger is not None
        try:
            turn = assistant.handle("refund ₹300 for my broken mug", order_id="ORD-1001")
            assert turn.decision.action is AgentAction.APPROVE
            assert turn.decision.amount_paise == 30_000
            assert turn.policy_blocked is False
            assert turn.prompt_tokens > 0 and turn.completion_tokens > 0
        finally:
            summary = logger.close()

        assert summary["pass_count"] == 1
        records = read_run(tmp_path / "reports" / "runs" / f"{logger.run_id}.jsonl")
        header = records[0]
        assert header["params"]["provider"] == "mock"
        assert header["artifact_digest"]  # prompts linked to the run (AST-1)
        case = next(r for r in records if r["type"] == "case")
        assert case["details"]["action"] == "approve"
        assert case["details"]["amount_paise"] == 30_000

    def test_refuse_above_cap(self) -> None:
        assistant, _ = make_assistant()
        turn = assistant.handle("I demand a ₹5,000 refund right now", order_id="ORD-2")
        assert turn.decision.action is AgentAction.REFUSE
        assert turn.decision.amount_paise == 500_000

    def test_ask_info_when_order_id_blank(self) -> None:
        assistant, _ = make_assistant()
        turn = assistant.handle("refund ₹300 please", order_id="   ")
        assert turn.decision.action is AgentAction.ASK_INFO

    def test_ask_info_when_no_amount(self) -> None:
        assistant, _ = make_assistant()
        turn = assistant.handle("hello I want a refund", order_id="ORD-3")
        assert turn.decision.action is AgentAction.ASK_INFO


class TestPolicyGuard:
    def test_non_compliant_model_is_blocked_in_code(self) -> None:
        # The scripted model "approves" ₹6,000 - the guard must refuse it.
        rogue = MockClient(
            steps=[
                MockStep(
                    parsed={
                        "action": "approve",
                        "amount_paise": 600_000,
                        "order_id": "ORD-9",
                        "message": "sure, approved!",
                    }
                )
            ]
        )
        assistant, _ = make_assistant(client=rogue)
        turn = assistant.handle("refund ₹6000", order_id="ORD-9")
        assert turn.policy_blocked is True
        assert turn.decision.action is AgentAction.REFUSE

    def test_truncated_input_flagged(self) -> None:
        assistant, _ = make_assistant()
        turn = assistant.handle("refund ₹100 " + "y" * 9_000, order_id="ORD-4")
        assert turn.sanitized_input_truncated is True

    def test_control_characters_never_reach_the_model(self) -> None:
        spy = SpyMockClient()
        assistant = RefundAssistant(client=spy, settings=Settings(_env_file=None))
        assistant.handle("re\x00fund ₹\x1b200 please", order_id="ORD-5")
        sent_user = spy.requests[-1].messages[-1].content
        assert "\x00" not in sent_user
        assert "\x1b" not in sent_user
        assert "₹200" in sent_user  # content itself survives cleaning


class TestFailurePaths:
    def test_model_error_logged_and_reraised(self, tmp_path: Path) -> None:
        exploding = MockClient(steps=[MockStep(error=ModelClientError("provider down"), times=5)])
        assistant, logger = make_assistant(tmp_path, client=exploding)
        assert logger is not None
        with pytest.raises(ModelClientError, match="provider down"):
            assistant.handle("refund ₹100", order_id="ORD-6")
        summary = logger.close()
        assert summary["error_count"] == 1
        assert summary["pass_count"] == 0

    def test_transient_errors_retried_then_succeed(self) -> None:
        flaky = MockClient(
            steps=[
                MockStep(error=TransientModelError("503"), times=2),
                MockStep(
                    parsed={
                        "action": "approve",
                        "amount_paise": 10_000,
                        "order_id": "ORD-7",
                        "message": "ok",
                    }
                ),
            ]
        )
        assistant, _ = make_assistant(client=flaky)
        turn = assistant.handle("refund ₹100", order_id="ORD-7")
        assert turn.decision.action is AgentAction.APPROVE


class SpyMockClient(MockClient):
    """Records every request so tests can assert what actually reached the model."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> object:  # type: ignore[override]
        self.requests.append(request)
        return super().complete(request)
