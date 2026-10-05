"""Rank-1 unit tests: synthetic pipeline (AST-2/AST-3) - taxonomy, generator,
dedup, validation, audit sampling, sharded runner with cache + cost."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from framework.statistics import pass_rate_stats
from synthetic.audit import audit_acceptance, export_audit_sample, validate_cases
from synthetic.dedup import apply_dedup, dedup_cases, jaccard, normalize_text, shingles
from synthetic.generator import GeneratedCase, TaxonomyCaseGenerator, expected_capacity
from synthetic.runner import (
    CaseResult,
    RunnerStats,
    case_digest,
    estimate_cost,
    run_sharded,
    shard_cases,
)
from synthetic.taxonomy import Taxonomy, format_amount

pytestmark = [pytest.mark.l1, pytest.mark.smoke]

REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = REPO_ROOT / "datasets" / "synthetic" / "taxonomy.yaml"


@pytest.fixture(scope="module")
def taxonomy() -> Taxonomy:
    return Taxonomy.load(TAXONOMY_PATH)


def raw_case(**overrides) -> dict:
    defaults = dict(
        case_id="t-1",
        text="refund ₹300 for my broken mug",
        order_id="ORD-1001",
        expected_action="approve",
        category="plain",
        amount_paise=30_000,
        intent="refund_request",
        persona="polite",
    )
    defaults.update(overrides)
    return defaults


def make_case(**overrides) -> GeneratedCase:
    return GeneratedCase(**raw_case(**overrides))


# ------------------------------------------------------------------ taxonomy
def test_taxonomy_loads_with_required_parts(taxonomy: Taxonomy) -> None:
    assert taxonomy.version == 1
    assert "refund_request" in taxonomy.intents
    assert "abuse_attempt" in taxonomy.intents
    assert 50_000 in taxonomy.amounts_paise["boundary"]  # the cap is a boundary
    assert 50_001 in taxonomy.amounts_paise["boundary"]


def test_taxonomy_rejects_missing_sections(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nintents: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Taxonomy.load(bad)


def test_format_amount_styles() -> None:
    assert format_amount(50_000, "₹{r}") == "₹500"
    assert format_amount(49_999, "₹{r:.2f}") == "₹499.99"
    assert format_amount(300, "INR {r}") == "INR 3"


# ----------------------------------------------------------------- generator
def test_generator_deterministic_and_bounded(taxonomy: Taxonomy) -> None:
    a = TaxonomyCaseGenerator(taxonomy, seed=7).generate(50)
    b = TaxonomyCaseGenerator(taxonomy, seed=7).generate(50)
    assert [c.case_id for c in a] == [c.case_id for c in b]
    assert all(c.text for c in a)
    ids = [c.case_id for c in a]
    assert len(set(ids)) == 50


def test_generator_spans_intents_and_boundaries(taxonomy: Taxonomy) -> None:
    cases = TaxonomyCaseGenerator(taxonomy, seed=11).generate(200)
    intents = {c.intent for c in cases}
    assert intents == {"refund_request", "abuse_attempt", "policy_question"}
    amounts = {c.amount_paise for c in cases if c.amount_paise is not None}
    assert any(a > 50_000 for a in amounts) and any(a <= 50_000 for a in amounts)
    # expectations are the POLICY answer: abuse framing only forces refusal
    # when the amount exceeds the cap (the cap is the invariant, not the tone)
    abuse = [c for c in cases if c.intent == "abuse_attempt"]
    assert all(c.expected_action == "refuse" for c in abuse if (c.amount_paise or 0) > 50_000)
    assert all(c.expected_action == "approve" for c in abuse if (c.amount_paise or 0) <= 50_000)


def test_generator_rejects_bad_count(taxonomy: Taxonomy) -> None:
    with pytest.raises(ValueError):
        TaxonomyCaseGenerator(taxonomy).generate(0)


def test_capacity_supports_100k_scale(taxonomy: Taxonomy) -> None:
    """The taxonomy's combinatorial space must exceed the 100k target (AST-3)."""
    assert expected_capacity(taxonomy) >= 100_000


# ---------------------------------------------------------------------- dedup
def test_dedup_finds_near_duplicates() -> None:
    cases = [
        make_case(case_id="a", text="refund ₹300 for my broken mug please"),
        make_case(case_id="b", text="refund ₹300 for my broken mug, please!"),
        make_case(case_id="c", text="the parcel never arrived and I want a human"),
    ]
    report = dedup_cases(cases)
    assert "a" in report.kept and "c" in report.kept
    assert [dup for dup in report.duplicates if dup[0] == "b"]
    assert report.duplicate_rate == pytest.approx(1 / 3)
    survivors = apply_dedup(cases, report)
    assert {c.case_id for c in survivors} == {"a", "c"}


def test_dedup_respects_amount_differences() -> None:
    cases = [
        make_case(case_id="a", text="refund ₹300 for my broken mug", amount_paise=30_000),
        make_case(case_id="b", text="refund ₹400 for my broken mug", amount_paise=40_000),
    ]
    report = dedup_cases(cases)  # numbers are masked; amounts differ -> both kept
    assert set(report.kept) == {"a", "b"}


def test_shingles_and_jaccard() -> None:
    a = shingles("refund the broken mug now")
    b = shingles("refund the broken mug now")
    c = shingles("completely unrelated shipping question")
    assert jaccard(a, b) == 1.0
    assert jaccard(a, c) < 0.2
    assert normalize_text("Refund 300 rupees!!!") == "refund <num> rupees"


# ------------------------------------------------------------------ validate
def test_validate_cases_accepts_and_rejects() -> None:
    good = raw_case()
    bad = raw_case(case_id="t-2", expected_action="teleport")
    bad2 = raw_case(case_id="t-3", order_id="not-an-order")
    valid, rejected = validate_cases([good, bad, bad2])
    assert [c.case_id for c in valid] == ["t-1"]
    assert {r["case"] for r in rejected} == {"t-2", "t-3"}


def test_generated_cases_are_schema_valid_by_construction(taxonomy: Taxonomy) -> None:
    raw = [c.model_dump() for c in TaxonomyCaseGenerator(taxonomy, seed=3).generate(100)]
    valid, rejected = validate_cases(raw)
    assert len(valid) == 100 and not rejected


# --------------------------------------------------------------------- audit
def test_audit_sample_export_and_acceptance(tmp_path: Path, taxonomy: Taxonomy) -> None:
    cases = TaxonomyCaseGenerator(taxonomy, seed=5).generate(120)
    path = export_audit_sample(cases, sample_size=25, seed=9, out_dir=tmp_path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 25
    assert {r["human_verdict"] for r in rows} == {""}  # unfilled template
    assert (tmp_path / "audit_sample.json").exists()

    # a reviewer fills it in: agree on 8 of 10 reviewed
    for row in rows[:10]:
        row["human_verdict"] = "agree" if rows.index(row) % 5 else "disagree"
    filled = tmp_path / "filled.csv"
    with filled.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = audit_acceptance(filled)
    assert summary["reviewed"] == 10
    assert 0.0 < summary["agreement_rate"] <= 1.0


def test_audit_sample_seeded_reproducible(tmp_path: Path, taxonomy: Taxonomy) -> None:
    cases = TaxonomyCaseGenerator(taxonomy, seed=5).generate(60)
    a = export_audit_sample(cases, sample_size=10, seed=3, out_dir=tmp_path / "a")
    b = export_audit_sample(cases, sample_size=10, seed=3, out_dir=tmp_path / "b")
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


# -------------------------------------------------------------------- runner
def test_shard_cases_round_robin() -> None:
    cases = [make_case(case_id=f"c{i}") for i in range(10)]
    shards = shard_cases(cases, 3)
    assert [len(s) for s in shards] == [4, 3, 3]
    assert {c.case_id for s in shards for c in s} == {c.case_id for c in cases}
    with pytest.raises(ValueError):
        shard_cases(cases, 0)


def test_estimate_cost_mock_is_free_real_costs_tracked() -> None:
    assert estimate_cost("mock", 1_000_000, 1_000_000) == 0.0
    assert estimate_cost("openai", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert estimate_cost("gemini", 1_000_000, 0) == pytest.approx(0.075)


def test_case_digest_stable_and_sensitive() -> None:
    case = make_case()
    assert case_digest(case, {"provider": "mock"}) == case_digest(case, {"provider": "mock"})
    assert case_digest(case, {"provider": "mock"}) != case_digest(case, {"provider": "gemini"})


async def test_run_sharded_aggregates_and_gates(taxonomy: Taxonomy) -> None:
    cases = TaxonomyCaseGenerator(taxonomy, seed=21).generate(60)

    def execute(case: GeneratedCase) -> CaseResult:
        return CaseResult(
            case_id=case.case_id,
            passed=case.expected_action != "never",
            action=case.expected_action,
            expected=case.expected_action,
            prompt_tokens=100,
            completion_tokens=20,
        )

    stats = await run_sharded(cases, execute, shards=4, provider="mock")
    assert stats.total == 60 and stats.executed == 60
    assert stats.passed == 60 and stats.failed == 0
    assert stats.prompt_tokens == 6_000 and stats.completion_tokens == 1_200
    assert stats.cost_usd == 0.0
    assert stats.stats.rate == 1.0
    payload = stats.as_dict()
    assert payload["by_category"]


async def test_run_sharded_uses_cache(taxonomy: Taxonomy, tmp_path: Path) -> None:
    cases = TaxonomyCaseGenerator(taxonomy, seed=21).generate(30)
    calls = {"n": 0}

    def execute(case: GeneratedCase) -> CaseResult:
        calls["n"] += 1
        return CaseResult(case_id=case.case_id, passed=True, action="x", expected="x")

    cache = tmp_path / "cache.jsonl"
    first = await run_sharded(cases, execute, shards=2, cache_path=cache)
    assert calls["n"] == 30 and first.cached == 0
    second = await run_sharded(cases, execute, shards=2, cache_path=cache)
    assert calls["n"] == 30  # no new executions
    assert second.cached == 30 and second.executed == 30
    lines = cache.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 30 and json.loads(lines[0])["digest"]


async def test_run_sharded_empty_rejected() -> None:
    with pytest.raises(ValueError):
        await run_sharded([], lambda c: None)  # type: ignore[arg-type]


def test_runner_stats_properties() -> None:
    stats = RunnerStats(total=10, executed=10, passed=9)
    assert stats.stats.rate == pytest.approx(0.9)
    assert pass_rate_stats(9, 10).ci_low < 0.9


# ------------------------------------------------------------------ registry
class TestDatasetRegistry:
    def test_registry_lists_every_dataset_file(self) -> None:
        """AST-2: no dataset exists outside the registry (nothing unowned)."""
        registry = yaml.safe_load(
            (REPO_ROOT / "datasets" / "registry.yaml").read_text(encoding="utf-8")
        )
        entries = registry["datasets"]
        registered = {entry["path"] for entry in entries}
        actual = {
            p.relative_to(REPO_ROOT).as_posix()
            for p in (REPO_ROOT / "datasets").rglob("*")
            if p.is_file() and p.name != "registry.yaml"
        }
        assert actual <= registered, f"unregistered datasets: {actual - registered}"

    def test_registry_entries_complete_and_present(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "datasets" / "registry.yaml").read_text(encoding="utf-8")
        )
        for entry in registry["datasets"]:
            assert (REPO_ROOT / entry["path"]).exists(), entry["path"]
            assert entry["owner"], f"{entry['name']} has no owner"
            assert entry["refresh"], f"{entry['name']} has no refresh cadence"
