# Proctor vs AI-Native Test Platforms (testRigor / mabl / ACCELQ)

An honest feature-by-feature comparison. These platforms are commercial,
closed-source, and cloud-tied; Proctor is open-source, code-first, and runs
fully offline. "Where we lead" claims are backed by tests in this repository.

## Capability matrix

| Capability | testRigor / mabl / ACCELQ | Proctor | Evidence |
|---|---|---|---|
| Plain-English test authoring | ✅ core selling point | ✅ `framework/nltests.py` - Markdown specs compile to gated runs across 28 domain packs | `tests/acceptance/refunds.md`, `python -m framework.nltests <spec>` |
| Self-healing maintenance | ✅ auto-heals selectors | ✅ `framework/healer.py` - flaky/drift/bug classification from N seeded replays; **human-approved proposals only (GOV-1)**, never silent edits | `python -m framework.healer <golden.csv> <pack>` |
| Semantic (not exact-match) assertions | ✅ | ✅ "the reply mentions ..." + action-level assertions, CI reported | `framework/nltests.py` |
| Statistical gating (Wilson CI, N-repeat) | ❌ single-run asserts | ✅ every non-deterministic check; 19/20 correctly fails a 95% gate | `framework/statistics.py`, L2 suites |
| Prompt injection / jailbreak / DLP security suites | ❌ | ✅ 317-row labeled corpus, P=R=F1=1.000 | `datasets/adversarial/`, L8 |
| RAG quality gates (Recall@k, faithfulness...) | ❌ | ✅ Recall@5=1.0 @ 60 docs; faithfulness 1.0 | `framework/large_context.py`, L4/L6 |
| Calibrated LLM-as-judge | Partial (proprietary) | ✅ ρ=0.838 vs human labels, test-enforced | `evals/calibrate.py` |
| Framework self-validation (mutation testing) | ❌ | ✅ 23/23 injected faults caught, 0 false alarms | `benchmark_framework_accuracy` |
| Domain breadth | Generic authoring | 28 packs / 80 app domains, executable probes | `domains/appdomains.py` |
| Circuit breakers / MCP contract testing | ❌ | ✅ 4 breakers + JSON-RPC suites | L7/L3 |
| Offline determinism / $0 runs | ❌ cloud-required | ✅ no keys, no network, 278 cases/s | CI runs |
| SOC 2 evidence generation | Partial (enterprise tiers) | ✅ evidence packs (never compliance claims) | `evidence/soc2.py` |
| Visual/UI low-code recording | ✅ | ❌ (browser journeys use Playwright code) | P3 in TODO |
| Cloud grid / parallel execution infra | ✅ managed | ❌ (pytest-xdist locally; workflows in GH Actions) | — |
| Vendor SSO / enterprise admin | ✅ | ❌ out of scope for an OSS framework | — |

## Where Proctor deliberately differs

1. **Healing with accountability.** mabl-style auto-heal can silently mask
   real regressions. Proctor's healer classifies (flaky vs drift vs bug),
   writes a proposal to `reports/heal/`, and changes nothing until a human
   marks `approved=yes` - the same GOV-1 principle as release sign-off.
2. **Authoring is plain-English, gating is statistical.** A testRigor step
   asserts once; a Proctor NL case runs N times and reports the pass rate
   with a confidence interval - because AI outputs are probabilistic.
3. **You own everything.** Specs, goldens, corpora, proposals, dashboards and
   evidence are files in your repo, versioned with your code - no vendor
   lock-in, no cloud dependency, no per-seat cost.

## What we honestly lack (tracked)

Visual low-code recording and a managed execution grid are the two real gaps;
both are tooling, not methodology, and sit behind Playwright install (P3) and
infra decisions. See docs/TODO.md.
