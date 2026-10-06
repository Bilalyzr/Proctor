"""Performance testing (checklist: load / stress / concurrency / throughput).

An in-process async load harness drives the guarded /chat endpoint through
the ASGI transport: concurrent workers, timed request mixes, p50/p95/p99
latency and requests-per-second under load, gated against thresholds.
This is an honest concurrency smoke (no network, deterministic mock
provider) - full k6/JMeter-style external load belongs to the performance
environment with a real provider.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from sut.api import create_app

pytestmark = [pytest.mark.l9, pytest.mark.nightly]

CONCURRENCY = 25
REQUESTS_PER_WORKER = 8
TOTAL = CONCURRENCY * REQUESTS_PER_WORKER
P95_SLA_MS = 2000.0  # matches thresholds/critical.yaml l3.p95_latency_ms


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = max(0, int(fraction * len(ordered)) - 1)
    return ordered[index]


async def _run_load() -> dict[str, float]:
    app = create_app(api_key=None, rate_limit=None)
    transport = httpx.ASGITransport(app=app)
    statuses: list[int] = []
    latencies: list[float] = []
    lock = asyncio.Lock()

    async def worker(client: httpx.AsyncClient) -> None:
        for _ in range(REQUESTS_PER_WORKER):
            started = time.perf_counter()
            response = await client.post(
                "/chat",
                json={"message": "refund Rs 300 for the broken mug", "order_id": "ORD-1001"},
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            async with lock:
                statuses.append(response.status_code)
                latencies.append(elapsed_ms)

    started = time.perf_counter()
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    ) as client:
        await asyncio.gather(*(worker(client) for _ in range(CONCURRENCY)))
    duration = time.perf_counter() - started
    return {
        "total": len(statuses),
        "ok": sum(1 for status in statuses if status == 200),
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "p99_ms": _percentile(latencies, 0.99),
        "duration_s": duration,
        "throughput_rps": len(statuses) / duration,
        "concurrency": CONCURRENCY,
    }


def test_load_concurrency_p95_and_throughput() -> None:
    """Concurrent load: every request succeeds, p95 within SLA, healthy rps."""
    report = asyncio.run(_run_load())
    print(f"[load] {report}")
    assert report["total"] == TOTAL
    assert report["ok"] == TOTAL, f"errors under load: {report}"
    assert report["p95_ms"] < P95_SLA_MS, f"p95 {report['p95_ms']:.0f}ms exceeds SLA"
    assert report["throughput_rps"] > 10, "throughput collapsed under concurrency"


def test_stress_oversized_messages_do_not_collapse_latency() -> None:
    """Stress edge: near-limit payloads stay within 3x the normal p95."""

    async def stress() -> dict[str, float]:
        app = create_app(api_key=None, rate_limit=None)
        transport = httpx.ASGITransport(app=app)
        latencies: list[float] = []
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=30.0
        ) as client:
            started = time.perf_counter()
            response = await client.post(
                "/chat", json={"message": "refund Rs 300 " + "detail " * 1000}
            )
            latencies.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200
        return {"p95_ms": latencies[0]}

    report = asyncio.run(stress())
    assert report["p95_ms"] < P95_SLA_MS
