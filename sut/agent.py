"""The refund assistant agent (SUT core).

Pipeline per turn: sanitize input -> extract amount hints -> one model call with
a structured-output schema -> code-side policy guard (the Rs 500 cap is
enforced in *code*, after the model) -> structured run-log record.

The Week-1 exit gate ("one model call logged end to end") is exactly one pass
through :meth:`RefundAssistant.handle` under the MOCK provider with a
:class:`~framework.runlog.RunLogger` attached.
"""

from __future__ import annotations

from typing import Any

from clients.base import (
    BaseClient,
    ChatMessage,
    CompletionRequest,
    ModelClient,
    ModelClientError,
    StructuredOutputError,
)
from framework.config import Settings
from framework.runlog import RunLogger
from sut.policy import AmountParsingError, enforce_policy, parse_amount
from sut.prompts import SYSTEM_PROMPT
from sut.sanitize import sanitize_input
from sut.schemas import AgentDecision, AgentTurn


class RefundAssistant:
    """One trained-policy turn machine around a provider-agnostic client."""

    def __init__(
        self,
        client: ModelClient,
        *,
        settings: Settings | None = None,
        run_logger: RunLogger | None = None,
    ) -> None:
        self.client = client
        self.settings = settings if settings is not None else Settings(_env_file=None)
        self.run_logger = run_logger
        self._turn_counter = 0

    def handle(
        self,
        user_text: str,
        *,
        order_id: str | None = None,
        seed: int | None = None,
    ) -> AgentTurn:
        """Process one user message and return the guarded decision."""
        self._turn_counter += 1
        case_id = f"refund-turn-{self._turn_counter:04d}"
        normalized_order = (order_id or "").strip() or None

        sanitized = sanitize_input(
            user_text,
            max_chars=self.settings.sanitize_max_chars,
            strip_markup=self.settings.sanitize_strip_markup,
        )
        try:
            amount = parse_amount(sanitized.text)
        except AmountParsingError:
            amount = None

        request = CompletionRequest(
            messages=[
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content=sanitized.text),
            ],
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            seed=self.settings.seed if seed is None else seed,
            response_format=AgentDecision,
            hints={"amount_paise": amount, "order_id": normalized_order},
        )

        try:
            response = self._complete(request)
        except ModelClientError:
            self._log(case_id, "error", {"order_id": normalized_order})
            raise

        parsed = response.parsed
        if not isinstance(parsed, AgentDecision):
            msg = "model client returned no parsed AgentDecision"
            raise StructuredOutputError(msg)

        decision, blocked = enforce_policy(parsed)
        self._log(
            case_id,
            "pass",
            {
                "action": decision.action.value,
                "amount_paise": decision.amount_paise,
                "order_id": decision.order_id,
                "policy_blocked": blocked,
                "input_truncated": sanitized.truncated,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            },
        )
        return AgentTurn(
            decision=decision,
            policy_blocked=blocked,
            sanitized_input_truncated=sanitized.truncated,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    # ------------------------------------------------------------------ internals
    def _complete(self, request: CompletionRequest) -> Any:
        if isinstance(self.client, BaseClient):
            return self.client.complete_with_retry(request)
        return self.client.complete(request)

    def _log(self, case_id: str, status: str, details: dict[str, Any]) -> None:
        if self.run_logger is not None:
            self.run_logger.log_case(case_id=case_id, status=status, layer="l1", details=details)
