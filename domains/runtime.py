"""Generic domain agent: one pipeline for every vertical.

Same architecture as the refund assistant, parameterized by a DomainPack:
sanitize -> parse facts -> model call with the pack's schema (the MOCK acts
as a compliant model via pack hints; rogue behavior is injectable via
MockStep scripts exactly as in the refund suites) -> code-side policy guard
-> structured turn. Defense in depth: even a rogue model cannot produce a
policy-violating decision.
"""

from __future__ import annotations

from typing import Any

from clients.base import BaseClient, ChatMessage, CompletionRequest, ModelClient
from clients.mock import MockClient
from domains.base import DomainPack, DomainTurn
from framework.config import Settings
from sut.sanitize import sanitize_input


class DomainAgent:
    """Runs one user turn through a pack's model path and policy guard."""

    def __init__(
        self,
        pack: DomainPack,
        client: ModelClient | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.pack = pack
        self.settings = settings if settings is not None else Settings(_env_file=None)
        self.client: ModelClient = (
            client
            if client is not None
            else MockClient(
                settings.model_name_for("mock") if settings else "mock", seed=self.settings.seed
            )
        )

    def handle(self, text: str, context: dict[str, Any] | None = None) -> DomainTurn:
        context = context or {}
        sanitized = sanitize_input(
            text,
            max_chars=self.settings.sanitize_max_chars,
            strip_markup=self.settings.sanitize_strip_markup,
        )
        facts = self.pack.policy.parse(sanitized.text, context)
        request = CompletionRequest(
            messages=[
                ChatMessage(role="system", content=self.pack.system_prompt),
                ChatMessage(role="user", content=sanitized.text),
            ],
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            seed=self.settings.seed,
            response_format=self.pack.schema,
            hints=self.pack.compliant_hints(facts),
        )
        if isinstance(self.client, BaseClient):
            response = self.client.complete_with_retry(request)
        else:  # pragma: no cover - protocol fallback
            response = self.client.complete(request)
        parsed = response.parsed
        if not isinstance(parsed, self.pack.schema):
            from clients.base import StructuredOutputError

            raise StructuredOutputError("model client returned the wrong schema type")
        final, blocked = self.pack.policy.enforce(parsed, facts)
        return DomainTurn(decision=final, policy_blocked=blocked, raw_decision=parsed)
