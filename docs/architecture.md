# Architecture

The framework implements the blueprint's nine-layer AI testing pyramid: a layer
runs only after the one beneath it passes (executable via `make gate` from
Phase 2 onward), every layer's gate reads versioned thresholds from
`thresholds/`, and non-deterministic checks run N times with pass-rate +
confidence-interval decisions.

## The pyramid

```
Rank 9  E2E journeys .............. Playwright + HTTP fallback        (Phase 6)
Rank 8  AI security ............... injection, DLP, scans, evidence   (Phase 6)
Rank 7  Agentic ................... tools, trajectories, breakers     (Phase 5)
Rank 6  RAG quality ............... RAGAS-style 4 metrics             (Phase 3)
Rank 5  LLM output ................ schema/style assertions           (Phase 2+)
Rank 4  Retrieval ................. ingestion, Recall@k, MRR          (Phase 3)
Rank 3  API integration ........... MCP/HTTP contracts                (Phase 5)
Rank 2  Prompt testing ............ boundary/negative/policy suites   (Phase 2)
Rank 1  Baseline unit ............. pytest, >=85% branch coverage     (Phase 1)
```

## Component map

```
framework/            harness core - no test layer owns it
  config.py           pydantic-settings; env-only secrets; EVL-2 params
  requirements.py     canonical registry of the 31 requirement IDs
  statistics.py       Wilson CI, pass-rate/max gates, Spearman rho
  artifacts.py        SHA-256 artifact snapshots (AST-1)
  runlog.py           JSONL run logs + manifests, one per suite run (AST-1)
  thresholds.py       versioned per-risk-tier gates (GOV-2)
  gates.py            ordered pyramid execution: failure stops the climb
  gate_runner.py      `make gate` CLI; --release requires human sign-off
  signoff.py          GOV-1 human sign-off records (digest-verified)
  repeat.py           N-repeat runner: pass rate + CI, failure seeds (EVL-1)
  feedback.py         thumbs/retries -> regression cases (PRD-3)
  diff_eval.py        old-vs-new differential evaluation, go/no-go (GOV-5)

clients/              provider-agnostic model client (LiteLLM-style surface)
  base.py             messages/requests/responses, retries, acomplete
  mock.py             deterministic MOCK: schema synthesis, refund persona,
                      failure-injection scripts (offline CI backbone)
  gemini/anthropic/openai  adapters with injectable transports (lazy SDKs)
  factory.py          Settings -> client; real providers fail fast keyless

sut/                  the system under test: ShopFast refund assistant
  prompts/schemas     versioned prompt; Pydantic AgentDecision contract
  policy.py           the Rs 500 cap: parsing, evaluation, code-side guard
  sanitize.py         control chars / markup / size cleaning (EVL-2)
  agent.py            single-turn assistant (rank 2/5 target)
  agent_loop.py       agentic loop: planner -> tools -> breakers -> tokens
  mcp_server.py       JSON-RPC 2.0 MCP server (stdio + in-memory transports)
  tools/              order_lookup, issue_refund (cap+ledger), escalate
  rag/                loader (md/txt/pdf_lite), chunking, hashing embedder,
                      in-memory store, retrieval pipeline, ingestion verify
  api.py + web/       FastAPI app + chat UI (guardrails inline; rank-9 E2E)

breakers/             AGT-1..4: recursion, state-repeat, duplicate-call hash,
                      step budget - every trip logged with an explanation

guardrails/           SEC-1..4 + PRD-1: injection classifier (direct/indirect,
                      base64), DLP (Luhn-gated PANs, PII, confidential),
                      infra masking (keys/paths/ports), brand safety,
                      runtime pipeline (inbound/outbound, rule-level logging),
                      redteam wrappers (Garak/PyRIT/promptfoo), repo scanners

evals/                RAGAS-style metrics (4, offline reference engine),
                      MockJudge + Spearman calibration (EVL-4)

synthetic/            taxonomy -> generator -> dedup -> validation -> audit
                      sample -> sharded async runner (cache + cost, AST-3)

telemetry/            metrics (Prometheus render), PSI drift bands,
                      published HTML dashboard + Grafana-style spec (PRD-2/GOV-3)

evidence/             SOC 2 Type 2 evidence packs - evidence only, never a
                      compliance claim (SEC-5)

tests/l1_unit ... l9_e2e/    one folder per pyramid rank, marker-selected;
                      tests/l1_unit/test_traceability.py ratches all 31 IDs
```

## Key decisions

- **Offline first.** `AIQA_PROVIDER=mock` (the default) runs everything with no
  keys, no network, deterministic outputs. Real providers activate only via env
  keys; adapters import SDKs lazily and raise `ProviderNotConfigured` otherwise.
  Adapters take injectable `transport` callables, so wire mapping is fully unit
  tested without any SDK installed.
- **Money is integers.** Amounts are paise (`₹500 == 50_000`), parsed via
  `Decimal`, rounded half-up; never floats.
- **Defense in depth.** The model decides, but `sut.policy.enforce_policy`
  re-checks every approval in code - a jailbroken model cannot push an over-cap
  refund through the assistant. The mock's default persona is compliant;
  non-compliance is injected explicitly by tests to prove the guard catches it.
- **Statistics, not luck.** Gates compare the Wilson CI *lower bound* to the
  threshold by default: 19/20 does not clear a 0.95 gate.
- **Traceability is executable.** `framework/requirements.py` is the canonical
  registry; `docs/traceability.md` is parsed by a test that ratchets each phase.

## Run artifacts (AST-1)

Every suite run writes `reports/runs/<run_id>.jsonl` (header with generation
params + artifact digest, one record per case, footer summary) and
`reports/manifests/<run_id>.json` (per-file SHA-256 of prompts, configs and
datasets used by that run). Later phases append retrieval indexes, judge
configs and evidence packs to the same manifest mechanism.
