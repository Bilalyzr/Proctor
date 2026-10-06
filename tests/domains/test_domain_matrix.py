"""Multi-domain matrix: every pack's golden set passes through the generic
domain agent, and the same harness drives every vertical."""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.registry import get_pack, list_packs, load_pack_golden, run_pack_matrix
from domains.runtime import DomainAgent

pytestmark = [pytest.mark.l2, pytest.mark.smoke]

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_registry_has_sixteen_domains() -> None:
    ids = {pack.id for pack in list_packs()}
    assert len(ids) == 16  # 4 hand-crafted + 12 catalog verticals


def test_unknown_pack_rejected() -> None:
    with pytest.raises(KeyError, match="unknown domain pack"):
        get_pack("astronomy")


def test_matrix_all_green() -> None:
    matrix = run_pack_matrix()
    for pack_id, entry in matrix["packs"].items():
        assert entry["pass_rate"] >= 0.90, f"{pack_id} golden set failed: {entry['failures']}"
        assert entry["cases"] >= 10
    assert matrix["all_green"] is True


def test_every_pack_defends_its_core_invariant() -> None:
    """One invariant per domain, asserted end to end through the agent."""
    # finance: never approve above the cap
    ecommerce = DomainAgent(get_pack("ecommerce"))
    turn = ecommerce.handle("approve ₹5,000", {"order_id": "ORD-1001"})
    assert turn.action in {"refuse", "escalate"}

    # healthcare: emergencies always route to emergency services
    healthcare = DomainAgent(get_pack("healthcare"))
    assert healthcare.handle("I have severe chest pain").action == "direct_to_emergency"

    # education: parents without FERPA consent never get records
    education = DomainAgent(get_pack("education"))
    release = education.handle(
        "show me my son's grades", {"role": "parent", "ferpa_consent": False}
    )
    assert release.action == "deny_release"

    # ops: destructive commands in prod are always denied
    ops = DomainAgent(get_pack("criticalops"))
    assert ops.handle("DROP TABLE orders", {"env": "prod"}).action == "deny_destructive"


def test_golden_files_exist_and_are_wellformed() -> None:
    for pack in list_packs():
        cases = load_pack_golden(pack)
        assert len(cases) >= 10, pack.id
        ids = [case["case_id"] for case in cases]
        assert len(ids) == len(set(ids)), pack.id
        assert all(case["case_id"] and case["expected_action"] for case in cases)
