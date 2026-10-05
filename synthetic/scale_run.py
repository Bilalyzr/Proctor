"""CLI: ``python -m synthetic.scale_run [--cases N] [--shards S] [--tier critical]``.

End-to-end scale exercise: taxonomy -> generate -> dedup -> validate -> audit
sample -> sharded execution with cache and cost tracking -> statistical gate.
Nightly CI runs a small N (600); the weekly workflow scales toward the 100k
blueprint target (mock provider: free and fast; real providers via env keys).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from clients.mock import MockClient
from framework.config import Settings
from framework.statistics import evaluate_rate_gate
from framework.thresholds import load_thresholds
from sut.agent import RefundAssistant
from synthetic.audit import export_audit_sample
from synthetic.dedup import apply_dedup, dedup_cases
from synthetic.generator import GeneratedCase, TaxonomyCaseGenerator
from synthetic.runner import CaseResult, run_sharded
from synthetic.taxonomy import Taxonomy

REPO_ROOT = Path(__file__).resolve().parents[1]


def execute_case(assistant: RefundAssistant) -> Callable[[GeneratedCase], CaseResult]:
    def run(case: GeneratedCase) -> CaseResult:
        turn = assistant.handle(case.text, order_id=case.order_id, seed=case.seed)
        return CaseResult(
            case_id=case.case_id,
            passed=turn.decision.action.value == case.expected_action,
            action=turn.decision.action.value,
            expected=case.expected_action,
            prompt_tokens=turn.prompt_tokens,
            completion_tokens=turn.completion_tokens,
        )

    return run


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Synthetic scale run")
    parser.add_argument("--cases", type=int, default=600)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--tier", default=None)
    parser.add_argument("--cache", default="datasets/synthetic/cache/scale_run.jsonl")
    args = parser.parse_args(argv)

    settings = Settings(_env_file=None)
    tier = args.tier or settings.tier
    thresholds = load_thresholds(tier, REPO_ROOT / "thresholds")
    taxonomy = Taxonomy.load(REPO_ROOT / "datasets" / "synthetic" / "taxonomy.yaml")

    cases = TaxonomyCaseGenerator(taxonomy, seed=settings.seed).generate(args.cases)
    dedup_report = dedup_cases(cases)
    cases = apply_dedup(cases, dedup_report)
    audit_path = export_audit_sample(
        cases,
        sample_size=min(30, len(cases)),
        seed=settings.seed,
        out_dir=REPO_ROOT / "reports" / "audit",
    )
    assistant = RefundAssistant(
        MockClient(settings.model_name_for("mock"), seed=settings.seed), settings=settings
    )
    stats = await run_sharded(
        cases,
        execute_case(assistant),
        shards=args.shards,
        params=settings.generation_params(),
        cache_path=REPO_ROOT / args.cache,
        provider="mock",
    )
    gate = evaluate_rate_gate(
        "synthetic-scale",
        stats.passed,
        stats.total,
        thresholds.gate_value("l2", "min_pass_rate"),
        "point",
    )
    report = {
        "cases_requested": args.cases,
        "cases_after_dedup": len(cases),
        "duplicate_rate": round(dedup_report.duplicate_rate, 4),
        "audit_sample": str(audit_path),
        "run": stats.as_dict(),
        "gate": gate.as_dict(),
        "provider": "mock (offline; real-provider numbers need API keys)",
    }
    out = REPO_ROOT / "reports" / f"scale_run_{args.cases}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("cases_requested", "cases_after_dedup", "duplicate_rate", "run", "gate")
            },
            indent=2,
        )
    )
    print(f"[scale] report: {out}")
    return 0 if gate.passed else 1


def main(argv: list[str] | None = None) -> int:
    import asyncio

    return asyncio.run(main_async(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
