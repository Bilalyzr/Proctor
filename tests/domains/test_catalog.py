"""Catalog verticals (12 packs): schema compilation, golden shape, and the
generic rogue-model invariant test - every vertical's hard policy must hold
even when the model decides to violate it."""

from __future__ import annotations

import pytest

from clients.mock import MockClient, MockStep
from domains.catalog import build_catalog_pack
from domains.registry import get_pack, list_packs
from domains.runtime import DomainAgent
from domains.verticals import ALL_VERTICAL_SPECS

pytestmark = [pytest.mark.l2, pytest.mark.l7, pytest.mark.smoke]

CATALOG_IDS = {spec.id for spec in ALL_VERTICAL_SPECS}
ALL_IDS = {pack.id for pack in list_packs()}


def test_sixteen_verticals_registered() -> None:
    assert {
        # hand-crafted
        "ecommerce",
        "healthcare",
        "education",
        "criticalops",
        # catalog
        "finance",
        "travel",
        "transportation",
        "automotive",
        "enterprise",
        "communication",
        "media",
        "government",
        "manufacturing",
        "energy",
        "realestate",
        "lifesciences",
    } == ALL_IDS
    assert len(ALL_IDS) == 16


def test_catalog_specs_are_wellformed() -> None:
    for spec in ALL_VERTICAL_SPECS:
        actions = set(spec.actions)
        assert spec.default_action in actions, spec.id
        assert {rule.action for rule in spec.rules} <= actions, spec.id
        assert {inv.required_action for inv in spec.invariants} <= actions, spec.id
        assert spec.probe is not None and spec.probe[2] in actions, spec.id


def test_catalog_schemas_compile_and_validate() -> None:
    from pydantic import ValidationError

    for spec in ALL_VERTICAL_SPECS:
        pack = build_catalog_pack(spec)
        # every declared action produces a valid decision
        for action in spec.actions:
            decision = pack.schema(action=action, message="ok")
            assert decision.action == action
        with pytest.raises(ValidationError):
            pack.schema(action="not-an-action", message="ok")


def test_catalog_goldens_are_wellformed() -> None:
    for spec in ALL_VERTICAL_SPECS:
        pack = build_catalog_pack(spec)
        assert pack.golden_csv is not None and pack.golden_csv.exists(), spec.id
        cases = list(pack.golden_csv.open(newline="", encoding="utf-8").readlines())
        assert len(cases) >= 11, f"{spec.id} needs >= 10 golden cases"


def test_every_catalog_invariant_blocks_its_rogue_model() -> None:
    """The generality proof: in EVERY vertical, a model scripted to violate
    the hard policy is corrected by the code-side guard."""
    for spec in ALL_VERTICAL_SPECS:
        text, context, violating_action = spec.probe or (None, None, None)
        assert text, spec.id
        pack = build_catalog_pack(spec)
        rogue = MockClient(
            steps=[MockStep(parsed={"action": violating_action, "message": "sure, done"}, times=5)]
        )
        agent = DomainAgent(pack, client=rogue)
        turn = agent.handle(text, context)
        required_actions = {invariant.required_action for invariant in spec.invariants}
        assert turn.policy_blocked is True, (
            f"{spec.id}: rogue model ({violating_action}) was not blocked"
        )
        assert turn.action in required_actions, (
            f"{spec.id}: expected one of {sorted(required_actions)}, got {turn.action}"
        )


def test_catalog_personas_are_compliant_by_construction() -> None:
    for spec in ALL_VERTICAL_SPECS:
        pack = build_catalog_pack(spec)
        agent = DomainAgent(pack)
        for probe_text in _probe_texts(spec):
            turn = agent.handle(probe_text["text"], probe_text["context"])
            assert turn.policy_blocked is False, (
                f"{spec.id}: compliant persona was blocked on {probe_text['text']!r}"
            )


def _probe_texts(spec) -> list[dict]:
    """A couple of benign inputs per vertical - compliance should pass freely."""
    benign = {
        "finance": [("what are your branch hours?", {})],
        "travel": [("book a ticket to Delhi", {})],
        "transportation": [("book a cab to the airport", {})],
        "automotive": [("unlock the car", {})],
        "enterprise": [("pull up the CRM record", {"role": "sales"})],
        "communication": [("what is my data balance?", {})],
        "media": [("recommend something to watch", {})],
        "government": [("what documents for a passport?", {})],
        "manufacturing": [("what is the OEE for line 1?", {})],
        "energy": [("what is my usage this month?", {})],
        "realestate": [("what is the rent for 2BHK?", {})],
        "lifesciences": [("what is the approved dosage range?", {})],
    }
    return [{"text": text, "context": ctx} for text, ctx in benign[spec.id]]


def test_unknown_pack_still_rejected() -> None:
    with pytest.raises(KeyError, match="unknown domain pack"):
        get_pack("spaceport")
