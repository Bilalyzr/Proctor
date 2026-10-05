"""Deterministic MOCK provider - the offline backbone of the framework.

Design contract:

* **Deterministic** - the same request (messages + seed + model) always yields
  the same response. N-repeat statistics therefore exercise real math on a
  simulated model; the harness is validated offline, and any provider can be
  swapped in later by changing one env var.
* **Schema-aware** - when ``response_format`` is set, the mock synthesizes a
  schema-valid instance (respecting enums, literals and numeric bounds) rather
  than free text, so structured-output paths are exercised end to end.
* **Hint-driven** - ``request.hints`` (extracted amounts, order IDs) steer
  synthesis so responses are coherent with the conversation.
* **Persona** - when the target schema looks like the refund assistant's
  decision model (an ``action`` enum plus ``amount_paise``), a built-in persona
  simulates a policy-*compliant* model. Non-compliance is injected explicitly
  via :class:`MockStep` scripts - which is precisely what the Phase 2+ breach
  suites need to prove the framework catches violations.
* **Failure injection** - scripted steps and ``flaky_rate`` produce errors,
  malformed output and transient failures for robustness testing.

The persona cap defaults to 50_000 paise (Rs 500) and must equal
``sut.policy.MAX_REFUND_PAISE``; ``tests/l1_unit/test_mock_client.py`` asserts
the two stay in sync.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

from clients._structured import parse_structured
from clients.base import (
    BaseClient,
    CompletionRequest,
    CompletionResponse,
    ModelClientError,
    StructuredOutputError,
    TokenUsage,
    TransientModelError,
)

# Default refund cap in paise; kept equal to sut.policy.MAX_REFUND_PAISE by test.
DEFAULT_REFUND_CAP_PAISE = 50_000

_APPROVE_MESSAGES = (
    "Your refund of {amount} has been approved and will return to your original "
    "payment method within 3-5 business days.",
    "Approved - I've queued a refund of {amount} for this order.",
)
_REFUSE_MESSAGES = (
    "I'm sorry, but refunds above {cap} require human approval, so I cannot "
    "approve {amount} automatically.",
    "That amount exceeds the {cap} automatic-refund limit. I can escalate this "
    "to a human agent if you'd like.",
)
_ASK_INFO_MESSAGES = (
    "I can help with that refund. Could you share your order ID and the refund amount?",
    "Sure - I just need your order ID and the amount to refund.",
)
_GENERIC_MESSAGES = (
    "Here's what I found for your request.",
    "Thanks - I've looked into it.",
    "Could you give me a little more detail?",
)
_NAMES = ("Asha", "Rahul", "Priya", "Vikram", "Meera", "Arjun", "Divya", "Kabir")
_REASONS = ("damaged item", "late delivery", "wrong item received", "duplicate charge")


def format_paise(amount_paise: int) -> str:
    """Render paise as a Rs-amount string (Rs symbol, 2 decimals when needed)."""
    rupees = amount_paise / 100.0
    text = f"{rupees:.2f}".rstrip("0").rstrip(".")
    return f"\u20b9{text}"


@dataclass(slots=True)
class MockStep:
    """One scripted response, consumed in order before default synthesis.

    ``times`` repeats the step for consecutive calls; ``when`` gates it on the
    request (still consumed in order). Exactly one of ``parsed``/``text``/
    ``error`` should be set.
    """

    text: str | None = None
    parsed: dict[str, Any] | None = None
    error: Exception | None = None
    times: int = 1
    when: Callable[[CompletionRequest], bool] | None = None
    transient: bool = True


@dataclass(slots=True)
class _PersonaDecision:
    action: str
    amount_paise: int | None
    message: str


class MockClient(BaseClient):
    """Seeded, fully offline model provider."""

    provider = "mock"
    default_model = "mock-refund-assistant-v1"

    def __init__(
        self,
        model: str | None = None,
        *,
        seed: int = 42,
        steps: list[MockStep] | None = None,
        flaky_rate: float = 0.0,
        refund_cap_paise: int = DEFAULT_REFUND_CAP_PAISE,
    ) -> None:
        super().__init__(model, seed=seed)
        if not 0.0 <= flaky_rate <= 1.0:
            msg = f"flaky_rate must be in [0, 1], got {flaky_rate}"
            raise ValueError(msg)
        if refund_cap_paise < 0:
            msg = "refund_cap_paise must be >= 0"
            raise ValueError(msg)
        self.flaky_rate = flaky_rate
        self.refund_cap_paise = refund_cap_paise
        self._queue: list[MockStep] = []
        for step in steps or []:
            self._queue.extend([step] * max(1, step.times))
        self._call_index = 0

    # ------------------------------------------------------------------ api
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        # flakiness is per-call (its own rng seeded by call order)
        if self.flaky_rate > 0.0:
            call_rng = random.Random(f"{self.seed}:{self._call_index}")
            self._call_index += 1
            if call_rng.random() < self.flaky_rate:
                raise TransientModelError("injected transient failure (flaky_rate)")

        rng = self._rng_for(request)
        step = self._next_step(request)
        if step is not None:
            return self._apply_step(step, request, rng)

        return self._synthesize(request, rng)

    # ----------------------------------------------------------- scripting
    def _next_step(self, request: CompletionRequest) -> MockStep | None:
        while self._queue:
            step = self._queue[0]
            if step.when is None or step.when(request):
                self._queue.pop(0)
                return step
            # gated step not applicable now; try the next one
            self._queue.pop(0)
        return None

    def _apply_step(
        self, step: MockStep, request: CompletionRequest, rng: random.Random
    ) -> CompletionResponse:
        if step.error is not None:
            if isinstance(step.error, ModelClientError):
                raise step.error
            raise ModelClientError(str(step.error)) from step.error
        if step.parsed is not None:
            if request.response_format is None:
                text = json.dumps(step.parsed)
                return self._response(text, request, parsed=None)
            text = json.dumps(step.parsed)
            step_parsed = parse_structured(text, request.response_format)
            return self._response(text, request, parsed=step_parsed)
        text = step.text if step.text is not None else ""
        parsed: BaseModel | None = None
        if request.response_format is not None:
            parsed = parse_structured(text, request.response_format)
        return self._response(text, request, parsed=parsed)

    # ------------------------------------------------------- default synth
    def _synthesize(self, request: CompletionRequest, rng: random.Random) -> CompletionResponse:
        if request.response_format is None:
            text = self._free_text(request, rng)
            return self._response(text, request, parsed=None)

        model_cls = request.response_format
        persona = self._persona_decision(model_cls, request.hints, rng)
        if persona is not None:
            text = json.dumps(
                {
                    "action": persona.action,
                    "amount_paise": persona.amount_paise,
                    "message": persona.message,
                },
                sort_keys=True,
            )
            parsed = parse_structured(text, model_cls)
            return self._response(text, request, parsed=parsed)

        values = {
            name: _value_for_field(name, field_info, rng, request.hints)
            for name, field_info in model_cls.model_fields.items()
        }
        text = json.dumps(values, sort_keys=True, default=str)
        parsed = parse_structured(text, model_cls)
        return self._response(text, request, parsed=parsed)

    def _persona_decision(
        self, model_cls: type[BaseModel], hints: dict[str, Any], rng: random.Random
    ) -> _PersonaDecision | None:
        """Refund persona: applies when the schema has action + amount_paise fields."""
        names = set(model_cls.model_fields)
        if not {"action", "amount_paise"} <= names:
            return None
        amount = _hint_for("amount_paise", hints)
        order_id = _hint_for("order_id", hints)
        if order_id is None:
            return _PersonaDecision("ask_info", None, rng.choice(_ASK_INFO_MESSAGES))
        if not isinstance(amount, int) or amount <= 0:
            return _PersonaDecision("ask_info", None, rng.choice(_ASK_INFO_MESSAGES))
        if amount <= self.refund_cap_paise:
            message = rng.choice(_APPROVE_MESSAGES).format(amount=format_paise(amount))
            return _PersonaDecision("approve", amount, message)
        message = rng.choice(_REFUSE_MESSAGES).format(
            amount=format_paise(amount), cap=format_paise(self.refund_cap_paise)
        )
        return _PersonaDecision("refuse", amount, message)

    def _free_text(self, request: CompletionRequest, rng: random.Random) -> str:
        last_user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        lowered = last_user.lower()
        if "refund" in lowered:
            amount = _hint_for("amount_paise", request.hints)
            if isinstance(amount, int) and amount > self.refund_cap_paise:
                return (
                    f"I can't approve refunds above {format_paise(self.refund_cap_paise)}. "
                    "I can escalate to a human agent."
                )
            return (
                "I can help with refund requests up to " + format_paise(self.refund_cap_paise) + "."
            )
        return rng.choice(_GENERIC_MESSAGES)

    # ----------------------------------------------------------- internals
    def _rng_for(self, request: CompletionRequest) -> random.Random:
        resolved = self._resolved(request)
        material = json.dumps(
            {
                "seed": resolved["seed"],
                "model": resolved["model"],
                "messages": [[m.role, m.content] for m in request.messages],
            },
            sort_keys=True,
        )
        digest = hashlib.blake2b(material.encode("utf-8"), digest_size=8).hexdigest()
        return random.Random(int(digest, 16))

    def _response(
        self,
        text: str,
        request: CompletionRequest,
        parsed: BaseModel | None,
    ) -> CompletionResponse:
        resolved = self._resolved(request)
        usage = TokenUsage(
            prompt_tokens=sum(len(m.content) // 4 + 4 for m in request.messages),
            completion_tokens=len(text) // 4 + 4,
        )
        return CompletionResponse(
            text=text,
            usage=usage,
            provider=self.provider,
            model=str(resolved["model"]),
            finish_reason="stop",
            parsed=parsed,
        )


# --------------------------------------------------------------------------
# generic schema synthesis helpers
# --------------------------------------------------------------------------


def _hint_for(field_name: str, hints: dict[str, Any]) -> Any:
    """Exact hint first, then substring match (``amount`` -> ``amount_paise``)."""
    if field_name in hints:
        return hints[field_name]
    lowered = field_name.lower()
    for key, value in hints.items():
        if value is not None and str(key).lower() in lowered:
            return value
    return None


def _unwrap(annotation: Any) -> Any:
    """Peel Annotated / Optional / Union down to concrete types (first branch)."""
    import types
    import typing

    # Annotated aliases carry __metadata__; the underlying type sits in __origin__.
    if hasattr(annotation, "__metadata__"):
        return _unwrap(annotation.__origin__)
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _unwrap(args[0])
    return annotation


def _is_literal(annotation: Any) -> bool:
    import typing

    return typing.get_origin(annotation) is typing.Literal


def _literal_args(annotation: Any) -> list[Any]:
    import typing

    return list(typing.get_args(annotation))


def _value_for_field(name: str, field_info: Any, rng: random.Random, hints: dict[str, Any]) -> Any:
    import typing

    annotation = _unwrap(field_info.annotation)
    hint = _hint_for(name, hints)
    if hint is not None:
        return hint

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return rng.choice(list(annotation)).value  # primitive, JSON-serializable
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {
            sub: _value_for_field(sub, fi, rng, hints)
            for sub, fi in annotation.model_fields.items()
        }
    if _is_literal(annotation):
        return rng.choice(_literal_args(annotation))

    lowered = name.lower()
    ge: float | None = None
    le: float | None = None
    for meta in field_info.metadata or ():
        # constraint markers (Ge/Le) carry lowercase attributes; duck-typed so
        # pydantic version differences cannot break synthesis
        if ge is None:
            ge = getattr(meta, "ge", None)
        if le is None:
            le = getattr(meta, "le", None)

    origin = typing.get_origin(annotation)
    if origin is list:
        return []
    if origin is dict:
        return {}

    if annotation is bool:
        return rng.random() < 0.8
    if annotation is int:
        low = int(ge) if ge is not None else 1
        high = int(le) if le is not None else low + 99
        return rng.randint(low, max(low, high))
    if annotation is float:
        low_f = float(ge) if ge is not None else 0.0
        high_f = float(le) if le is not None else low_f + 100.0
        return round(rng.uniform(low_f, high_f), 2)
    if annotation is str:
        if any(word in lowered for word in ("message", "text", "reason", "rationale")):
            return rng.choice(_REASONS)
        if "name" in lowered:
            return rng.choice(_NAMES)
        if "id" in lowered:
            return f"ORD-{1000 + rng.randint(0, 8999)}"
        return f"{lowered}-{rng.randint(0, 999)}"
    return None


__all__ = [
    "DEFAULT_REFUND_CAP_PAISE",
    "MockClient",
    "MockStep",
    "StructuredOutputError",
    "TransientModelError",
    "format_paise",
]
