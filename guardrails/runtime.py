"""Guardrail pipeline (PRD-1): inline interception of live traffic.

Inbound (before the model): injection defense + brand safety on input.
Outbound (before the user): DLP + infrastructure masking + brand safety on
the reply and on RAG context. Every block is logged as a GuardrailEvent with
the rule that fired; miss and false-positive rates come from the L8 suites.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guardrails.brand import BrandSafetyGuardrail
from guardrails.dlp import DLPGuardrail
from guardrails.infra_mask import InfraMaskGuardrail
from guardrails.injection import InjectionGuardrail


@dataclass(slots=True)
class GuardrailEvent:
    """One block/allow decision, with the rule that fired."""

    direction: str  # "inbound" | "outbound"
    rule: str | None
    blocked: bool
    fragment: str | None = None
    ts: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "rule": self.rule,
            "blocked": self.blocked,
            "fragment": self.fragment,
            "ts": self.ts,
        }


@dataclass(slots=True)
class PipelineVerdict:
    """Result of running the pipeline over one turn."""

    allowed: bool
    text: str
    events: list[GuardrailEvent] = field(default_factory=list)

    @property
    def blocking_rules(self) -> list[str]:
        return [event.rule or "unknown" for event in self.events if event.blocked]


class GuardrailPipeline:
    """Inline guardrails around one assistant turn."""

    def __init__(
        self,
        injection: InjectionGuardrail | None = None,
        dlp: DLPGuardrail | None = None,
        infra: InfraMaskGuardrail | None = None,
        brand: BrandSafetyGuardrail | None = None,
    ) -> None:
        self.injection = injection if injection is not None else InjectionGuardrail()
        self.dlp = dlp if dlp is not None else DLPGuardrail()
        self.infra = infra if infra is not None else InfraMaskGuardrail()
        self.brand = brand if brand is not None else BrandSafetyGuardrail()
        # bounded ring: a long-running server must not grow this forever
        self.events: deque[GuardrailEvent] = deque(maxlen=5000)

    # ----------------------------------------------------------------- inbound
    def check_inbound(self, text: str) -> PipelineVerdict:
        """Gate user input; blocking verdicts never reach the model."""
        events: list[GuardrailEvent] = []
        injection = self.injection.inspect(text, source="user")
        events.append(
            GuardrailEvent(
                "inbound",
                injection.rule if injection.blocked else None,
                injection.blocked,
                injection.matched_fragment,
            )
        )
        brand = self.brand.inspect_inbound(text)
        events.append(
            GuardrailEvent(
                "inbound", brand.rule if brand.blocked else None, brand.blocked, brand.fragment
            )
        )
        self.events.extend(events)
        allowed = not any(event.blocked for event in events)
        return PipelineVerdict(allowed=allowed, text=text if allowed else "", events=events)

    # ---------------------------------------------------------------- outbound
    def check_outbound(self, text: str, *, is_rag_context: bool = False) -> PipelineVerdict:
        """Mask and gate model output / retrieved context before display."""
        events: list[GuardrailEvent] = []
        dlp = self.dlp.mask(text)
        if dlp.masked:
            events.extend(
                GuardrailEvent("outbound", finding["rule"], True, finding["fragment"])
                for finding in dlp.findings
            )
        infra = self.infra.mask(dlp.text)
        if infra.masked:
            events.extend(
                GuardrailEvent("outbound", finding["rule"], True, finding["fragment"])
                for finding in infra.findings
            )
        brand = self.brand.inspect_outbound(infra.text)
        events.append(
            GuardrailEvent(
                "outbound", brand.rule if brand.blocked else None, brand.blocked, brand.fragment
            )
        )
        self.events.extend(events)
        allowed = not brand.blocked
        final_text = infra.text if allowed else ""
        # is_rag_context changes only the DEFAULT: benign-but-masked context
        # is returned for the model to use. Brand-blocked content is dropped
        # in both modes - never allowed=True with empty text.
        _ = is_rag_context
        return PipelineVerdict(allowed=allowed, text=final_text, events=events)

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        blocked = [event for event in self.events if event.blocked]
        return {
            "total": len(self.events),
            "blocked": len(blocked),
            "by_rule": sorted({event.rule for event in blocked if event.rule}),
        }

    def write_log(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps([event.as_dict() for event in self.events], indent=2),
            encoding="utf-8",
        )
        return target
