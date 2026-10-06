# Proctor — AI QA Testing Framework

An end-to-end, **offline-first** testing framework for AI applications: a
nine-layer testing pyramid with executable gates, statistical pass/fail
decisions (never a single lucky sample), runtime guardrails, circuit
breakers, synthetic test scaling to 100k cases, and multi-domain coverage —
built in Python with open-source tooling.

Proctor implements the *AI QA Testing Framework: End-to-End Blueprint*:
31 traced requirements (GOV / AST / EVL / RAG / AGT / MCP / SEC / PRD), a
six-week build roadmap executed as six phases, and human-owned gates —
AI evaluators never sign off a release alone.

---

## Why it exists

LLM applications are probabilistic, money-touching, and attackable. Classic
`assert expected == actual` cannot govern them. Proctor replaces binary
assertions with a **quality envelope**:

- every non-deterministic check runs **N times** and gates on the **pass rate
  with a Wilson confidence interval** — 19/20 correctly *fails* a 95% gate;
- **zero-breach policies** (a refund cap, a PHI rule, a destructive-command
  rule) are enforced in code *after* the model, so even a jailbroken or rogue
  model cannot push a violation through;
- **humans own the thresholds** — versioned per risk tier, digest-linked to
  every run, and required in a sign-off record before any release.

## The testing pyramid

```
Rank 9  E2E journeys .............. HTTP + Playwright journeys
Rank 8  AI security ............... injection, DLP, secret/port scans, SOC 2 evidence
Rank 7  Agentic ................... tools, trajectories, 4 circuit breakers
Rank 6  RAG quality ............... RAGAS-style metrics vs baseline
Rank 5  LLM output ................ schema/style quality envelope
Rank 4  Retrieval ................. ingestion checks, Recall@k, MRR, nDCG
Rank 3  API integration ........... MCP JSON-RPC 2.0 contracts
Rank 2  Prompt testing ............ boundary / negative / policy-breach suites
Rank 1  Baseline unit ............. pytest, >=85% branch coverage
```

A layer runs **only after the layer beneath it passes** (`make gate`), and
each layer's thresholds come from versioned `thresholds/<tier>.yaml` files.

## Multi-domain: all 16 industry verticals

The harness is vertical-agnostic; each industry plugs in as a **domain pack**.
All 16 industry groups are covered by 28 domain packs - and the full master
list of **80 application domains** (from BFSI to LegalTech to EV charging)
is initialized in `domains/appdomains.py`, each with an executable probe
test. Every pack has its own hard-policy engine, decision schema, golden
set, rogue-model invariant test and matrix entry:

Finance (BFSI/fintech/insurance) · Healthcare · Retail/E-commerce ·
Travel (airlines/hotels/booking) · Transportation (cab/logistics/fleet) ·
Automotive (connected cars/EV) · Education (LMS/exams) ·
Enterprise (ERP/CRM/HRMS/SaaS) · Communication (telecom/messaging) ·
Media (OTT/streaming/gaming) · Government (citizen/tax/identity) ·
Manufacturing (MES/PLM/IoT) · Energy (utilities/oil & gas) ·
Technology (cloud/DevOps/ops) · Real Estate · Life Sciences

Sample hard policies per vertical (the "Rs 500 cap" equivalents):
step-up auth for bank transfers ≥ Rs 10k, PHI/authorization gates in
hospitals, 24-hour airline cancellation windows, undeclared-hazmat shipment
denials, speed-limit-override denial in connected cars, manager approval for
>10% ERP discounts, OTP-gated number port-outs, parent PIN for minors'
in-app purchases, masked Aadhaar/PAN handling, safety-interlock bypass
denial in plants, permit-gated feeder shutdowns, 2-month deposit caps,
and mandatory adverse-event pharmacovigilance escalation.

```bash
python -m domains   # 28-pack matrix: golden sets + rogue-model invariants
```

Adding a 29th pack is one PackSpec + one golden CSV — see
[docs/domains.md](docs/domains.md) for the full 80-domain catalog.

## Quick start

```bash
git clone https://github.com/Bilalyzr/Proctor.git
cd Proctor

make setup     # or: python scripts/tasks.py setup   (Windows-friendly)
make test      # full suite with branch coverage gate (>=85%)
make lint      # ruff + mypy
make gate      # pyramid gates, bottom-up, from thresholds/<tier>.yaml
make nightly   # full regression as CI runs it
python -m domains        # multi-domain matrix report
python -m framework.gate_runner --release   # requires a human sign-off record
```

On Windows without `make`, use `python scripts/tasks.py <setup|test|lint|gate|nightly>`.

**No API keys needed.** Everything runs offline on a deterministic MOCK
provider (seeded, schema-synthesizing, with failure injection). Real
providers activate only via environment variables:

```bash
cp .env.example .env      # set AIQA_PROVIDER=gemini + AIQA_GEMINI_API_KEY=...
```

## What's inside

```
framework/     harness core: config, Wilson-CI statistics, N-repeat runner,
               run logging + artifact hashing, thresholds, gate chain,
               human sign-off (GOV-1), feedback-to-test, differential eval
clients/       provider-agnostic model client: deterministic MOCK + Gemini,
               Anthropic, OpenAI adapters (lazy SDKs, injectable transports)
sut/           the system under test: Rs 500-cap refund assistant, agent loop,
               MCP server + tools (order lookup / issue refund / escalate),
               RAG pipeline (md/txt/PDF loaders, chunking, embeddings, store)
breakers/      AGT-1..4: recursion limit, state-repeat, duplicate-call hash,
               step budget — every trip logged with an explanation
guardrails/    injection classifier (direct/indirect/base64), DLP
               (Luhn-gated PANs, PHI, student IDs), infra masking, brand
               safety, red-team wrappers, repo secret/port scanners
evals/         RAGAS-style metrics, calibrated LLM judge (Spearman >= 0.8)
synthetic/     taxonomy -> generation -> dedup -> validation -> human-audit
               sample -> sharded async runner with caching + cost tracking
telemetry/     Prometheus metrics, PSI drift detection, published dashboards
evidence/      SOC 2 Type 2 evidence packs (evidence only — no compliance claim)
domains/       domain packs: e-commerce, healthcare, education, critical ops
tests/         l1_unit ... l9_e2e + tests/domains/ — one folder per pyramid rank
thresholds/    versioned gates per risk tier (critical / high / standard)
datasets/      golden, synthetic, adversarial + retrieval benchmarks (registry)
docs/          architecture, domains, full requirements traceability
.github/       PR smoke, nightly regression, weekly 100k-scale workflows
```

## Requirements traceability (31/31)

Every requirement — GOV-1...5, AST-1...4, EVL-1...5, RAG-1/2, AGT-1...5,
MCP-1/2, SEC-1...5, PRD-1...3 — maps to code and tests in
[docs/traceability.md](docs/traceability.md), and a test enforces it: a
missing row, a dead path, or a phase backlog fails the build.

## Honest limitations

- Offline numbers validate the **harness**, not real models: the MOCK's
  golden-slice accuracy and RAGAS-style scores are real measurements of
  deterministic pipelines; real-model numbers need provider API keys.
- Ragas / Garak / PyRIT / Presidio / FAISS are optional extras behind
  interfaces; every report names the engine that produced a number.
- Playwright browser journeys skip (with instructions) when browsers aren't
  installed; HTTP journeys carry the L9 gate.
- SOC 2 Type 2 is an external audit of controls over time — this repo
  **generates evidence only** and never claims compliance.

## Docs

- [docs/architecture.md](docs/architecture.md) — pyramid, components, key decisions
- [docs/domains.md](docs/domains.md) — domain packs and how to add a vertical
- [docs/traceability.md](docs/traceability.md) — all 31 requirements mapped to code + tests
- [.env.example](.env.example) — configuration surface (pydantic-settings)
