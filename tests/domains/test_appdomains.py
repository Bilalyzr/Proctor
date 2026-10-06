"""The 80 application-domain catalog: every domain from the master list is
initialized, mapped to a pack, and holds its executable probe."""

from __future__ import annotations

import pytest

from domains.appdomains import APP_DOMAINS
from domains.registry import get_pack, list_packs
from domains.runtime import DomainAgent

pytestmark = [pytest.mark.l2, pytest.mark.smoke]


def test_all_eighty_domains_registered() -> None:
    numbers = sorted(domain.number for domain in APP_DOMAINS)
    assert numbers == list(range(1, 81))
    names = [domain.name for domain in APP_DOMAINS]
    assert len(names) == len(set(names)) == 80


def test_every_domain_maps_to_an_existing_pack() -> None:
    pack_ids = {pack.id for pack in list_packs()}
    for domain in APP_DOMAINS:
        assert domain.pack_id in pack_ids, f"#{domain.number} maps to missing pack {domain.pack_id}"
    # every pack carries at least one of the 80 domains
    mapped = {domain.pack_id for domain in APP_DOMAINS}
    assert mapped == pack_ids


@pytest.mark.parametrize(
    "domain",
    APP_DOMAINS,
    ids=lambda d: f"{d.number:02d}-{d.pack_id}",
)
def test_domain_probe_holds(domain) -> None:
    """The 'all 80 initialized' proof: each domain's probe scenario passes
    through its pack's agent and lands on the policy-correct action."""
    agent = DomainAgent(get_pack(domain.pack_id))
    turn = agent.handle(domain.probe_text, domain.probe_context)
    assert turn.action == domain.probe_expected, (
        f"#{domain.number} {domain.name}: {domain.probe_text!r} -> {turn.action}"
        f" (want {domain.probe_expected})"
    )
    # probes exercise policy paths, never rogue blocks
    assert turn.policy_blocked is False


def test_probe_coverage_per_pack() -> None:
    """No pack is initialized by name only: it must carry domain probes."""
    counts: dict[str, int] = {}
    for domain in APP_DOMAINS:
        counts[domain.pack_id] = counts.get(domain.pack_id, 0) + 1
    assert len(counts) == len(list_packs())
    assert all(count >= 1 for count in counts.values())
