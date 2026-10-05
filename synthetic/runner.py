"""Sharded scale runner (AST-3): asyncio + to_thread, response cache, cost.

Scales from a 600-case nightly slice to the 100k weekly run (blueprint
Section 13 "Scale execution"): cases are split into shards, executed with a
bounded worker pool, results cached by (case, parameters) digest, and token
cost tracked from a per-provider price table.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.statistics import PassRateStats, pass_rate_stats
from synthetic.generator import GeneratedCase

# indicative USD per 1k tokens (documented starting points; mock is free)
PRICE_TABLE_USD_PER_1K: dict[str, tuple[float, float]] = {
    "mock": (0.0, 0.0),
    "gemini": (0.000075, 0.0003),
    "anthropic": (0.003, 0.015),
    "openai": (0.00015, 0.0006),
}


@dataclass(slots=True)
class CaseResult:
    """Execution outcome for one case."""

    case_id: str
    passed: bool
    action: str
    expected: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False


@dataclass(slots=True)
class RunnerStats:
    """Aggregated run statistics."""

    total: int
    executed: int
    cached: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    shards: int = 1
    provider: str = "mock"
    by_category: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: {"passed": 0, "total": 0})
    )
    results: list[CaseResult] = field(default_factory=list)

    @property
    def stats(self) -> PassRateStats:
        return pass_rate_stats(self.passed, self.total)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "executed": self.executed,
            "cached": self.cached,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "duration_s": round(self.duration_s, 3),
            "shards": self.shards,
            "provider": self.provider,
            "pass_rate": round(self.stats.rate, 4),
            "ci_low": round(self.stats.ci_low, 4),
            "ci_high": round(self.stats.ci_high, 4),
            "by_category": {
                category: dict(counts) for category, counts in self.by_category.items()
            },
        }


def case_digest(case: GeneratedCase, params: dict[str, Any]) -> str:
    """Stable cache key for one case under one parameter set."""
    material = json.dumps({"case": case.model_dump(), "params": params}, sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()


def shard_cases(cases: list[GeneratedCase], shards: int) -> list[list[GeneratedCase]]:
    """Round-robin split into ``shards`` contiguous-free lists."""
    if shards < 1:
        raise ValueError("shards must be >= 1")
    buckets: list[list[GeneratedCase]] = [[] for _ in range(shards)]
    for index, case in enumerate(cases):
        buckets[index % shards].append(case)
    return buckets


def estimate_cost(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Indicative cost from the price table (mock provider costs nothing)."""
    price_in, price_out = PRICE_TABLE_USD_PER_1K.get(provider, (0.0, 0.0))
    return prompt_tokens / 1000 * price_in + completion_tokens / 1000 * price_out


def _load_cache(cache_path: Path) -> dict[str, dict[str, Any]]:
    if not cache_path.exists():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            cache[entry["digest"]] = entry["result"]
    return cache


def _append_cache(cache_path: Path, digest: str, result: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"digest": digest, "result": result}) + "\n")


async def run_sharded(
    cases: list[GeneratedCase],
    execute: Callable[[GeneratedCase], CaseResult],
    *,
    shards: int = 4,
    params: dict[str, Any] | None = None,
    cache_path: str | Path | None = None,
    provider: str = "mock",
) -> RunnerStats:
    """Execute cases across shards with caching and cost tracking.

    ``execute`` runs synchronously (assistant turns) and is pushed to threads
    under a bounded semaphore of ``shards * 4`` concurrent workers.
    """
    if not cases:
        raise ValueError("no cases to run")
    started = time.monotonic()
    params = params or {}
    cache_file = Path(cache_path) if cache_path else None
    cache = _load_cache(cache_file) if cache_file else {}
    stats = RunnerStats(total=len(cases), executed=0, shards=shards, provider=provider)
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(max(1, shards * 4))
    result_fields = set(CaseResult.__dataclass_fields__)
    categories = {case.case_id: case.category for case in cases}

    async def run_case(case: GeneratedCase) -> None:
        digest = case_digest(case, params)
        async with lock:
            cached_entry = cache.get(digest)
        if cached_entry is not None:
            result = CaseResult(
                cached=True,
                **{k: v for k, v in cached_entry.items() if k in result_fields and k != "cached"},
            )
        else:
            async with sem:
                result = await asyncio.to_thread(execute, case)
            if cache_file is not None:
                payload = {
                    "case_id": result.case_id,
                    "passed": result.passed,
                    "action": result.action,
                    "expected": result.expected,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                }
                async with lock:
                    _append_cache(cache_file, digest, payload)
                    cache[digest] = payload
        async with lock:
            stats.executed += 1
            stats.results.append(result)
            if result.cached:
                stats.cached += 1
            if result.passed:
                stats.passed += 1
                stats.by_category[categories[result.case_id]]["passed"] += 1
            else:
                stats.failed += 1
            stats.by_category[categories[result.case_id]]["total"] += 1
            stats.prompt_tokens += result.prompt_tokens
            stats.completion_tokens += result.completion_tokens
            if not result.cached:
                stats.cost_usd += estimate_cost(
                    provider, result.prompt_tokens, result.completion_tokens
                )

    await asyncio.gather(*(run_case(case) for case in cases))
    stats.duration_s = time.monotonic() - started
    return stats
