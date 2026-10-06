"""Declarative domain-pack catalog engine.

A vertical is a :class:`PackSpec`: ordered rules (first match decides) plus
hard invariants the code-side guard enforces *after* the model. The engine
compiles a spec into the same DomainPack interface the four hand-crafted
packs implement, so the matrix, gates, guardrails and CI treat all 16
verticals identically.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from domains.base import DomainFacts, DomainPack

Predicate = Callable[[dict[str, Any]], Any]  # truthy lambdas; bool() at use sites


@dataclass(slots=True)
class Rule:
    """One evaluation rule: when the predicate matches, decide this action."""

    predicate: Predicate
    action: str
    message: str


@dataclass(slots=True)
class Invariant:
    """A hard policy the guard enforces regardless of the model's decision."""

    predicate: Predicate
    required_action: str
    message: str


@dataclass(slots=True)
class PackSpec:
    """Everything needed to compile a vertical into a DomainPack."""

    id: str
    display_name: str
    prompt: str
    actions: list[str]
    default_action: str
    default_message: str
    extract: Callable[[str, dict[str, Any]], dict[str, Any]]
    rules: list[Rule]
    invariants: list[Invariant] = field(default_factory=list)
    golden_csv: Path | None = None
    risk_note: str = ""
    injection_rules: list[tuple[str, Any]] = field(default_factory=list)
    dlp_patterns: list[tuple[str, Any, str]] = field(default_factory=list)
    # rogue-model probe: (text, context, violating_action)
    probe: tuple[str, dict[str, Any], str] | None = None


class CatalogFacts(DomainFacts):
    """Facts for catalog packs: the spec's extracted dict rides in extras."""


def build_catalog_pack(spec: PackSpec) -> DomainPack:
    """Compile a PackSpec into a full DomainPack."""
    actions_tuple = tuple(spec.actions)
    action_field = Literal[actions_tuple]  # type: ignore[valid-type]
    schema: type[BaseModel] = create_model(
        f"{''.join(part.capitalize() for part in spec.id.split('_'))}Decision",
        __base__=BaseModel,
        action=(action_field, Field(...)),
        message=(str, Field(min_length=1, max_length=2000)),
    )

    def parse(text: str, context: dict[str, Any]) -> CatalogFacts:
        return CatalogFacts(text=text, extras=spec.extract(text, context))

    def evaluate(facts: DomainFacts) -> BaseModel:
        for rule in spec.rules:
            if rule.predicate(facts.extras):
                return schema(action=rule.action, message=rule.message)
        return schema(action=spec.default_action, message=spec.default_message)

    def enforce(decision: BaseModel, facts: DomainFacts) -> tuple[BaseModel, bool]:
        decided_action = getattr(decision, "action", None)
        for invariant in spec.invariants:
            if invariant.predicate(facts.extras) and decided_action != invariant.required_action:
                return schema(action=invariant.required_action, message=invariant.message), True
        return decision, False

    def persona(facts: DomainFacts) -> dict[str, Any]:
        for rule in spec.rules:
            if rule.predicate(facts.extras):
                return {"action": rule.action, "message": rule.message}
        return {"action": spec.default_action, "message": spec.default_message}

    policy = type(
        f"{spec.id.capitalize()}CatalogPolicy",
        (),
        {
            "parse": staticmethod(parse),
            "evaluate": staticmethod(evaluate),
            "enforce": staticmethod(enforce),
        },
    )()
    return DomainPack(
        id=spec.id,
        display_name=spec.display_name,
        policy=policy,
        schema=schema,
        system_prompt=spec.prompt,
        persona=persona,
        injection_rules=list(spec.injection_rules),
        dlp_patterns=list(spec.dlp_patterns),
        golden_csv=spec.golden_csv,
        risk_note=spec.risk_note,
    )
