"""Domain packs: plug any industry into the same testing pyramid.

A :class:`DomainPack` bundles everything layer-specific about a vertical:
facts parser, policy engine (evaluate + enforce guard), decision schema,
persona prompt, compliant-model hints, guardrail extensions and golden data.
The pyramid harness (gates, statistics, guardrail runtime, MCP tool registry,
synthetic pipeline) is shared infrastructure - packs make the framework test
e-commerce one week and hospital management the next.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel


class DomainFacts(BaseModel):
    """Parsed facts from one user turn (domain packs extend with extras)."""

    text: str
    wants_records: bool = False
    authorized: bool = False


class DomainPolicy(Protocol):
    """The contract every domain policy engine implements."""

    def parse(self, text: str, context: dict[str, Any]) -> DomainFacts: ...

    def evaluate(self, facts: DomainFacts) -> BaseModel: ...

    def enforce(self, decision: BaseModel, facts: DomainFacts) -> tuple[BaseModel, bool]: ...


@dataclass(slots=True)
class DomainPack:
    """One vertical's complete test-and-runtime definition."""

    id: str
    display_name: str
    policy: Any  # DomainPolicy implementation
    schema: type[BaseModel]
    system_prompt: str
    persona: Any  # facts -> dict of schema-field hints (compliant model)
    injection_rules: list[tuple[str, re.Pattern[str]]] = field(default_factory=list)
    dlp_patterns: list[tuple[str, re.Pattern[str], str]] = field(default_factory=list)
    golden_csv: Path | None = None
    risk_note: str = ""

    def compliant_hints(self, facts: DomainFacts) -> dict[str, Any]:
        """Hints the deterministic MOCK uses to act like a compliant model."""
        return self.persona(facts)


@dataclass(slots=True)
class DomainTurn:
    """One guarded domain-agent turn (mirrors AgentTurn)."""

    decision: BaseModel
    policy_blocked: bool = False
    raw_decision: BaseModel | None = None

    @property
    def action(self) -> str:
        value = getattr(self.decision, "action", None)
        return str(getattr(value, "value", value))
