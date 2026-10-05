# Requirements Traceability

Maps every requirement from blueprint Section 4 (31 IDs) to the code, config and
tests that satisfy it. This file is **executable**: `tests/l1_unit/test_traceability.py`
parses it on every run, fails if a row is missing or duplicated, if a `satisfied`
row points at a nonexistent path, or if a requirement due by the current build
phase is still open. Status flips from `planned` to `satisfied` only when the
phase's tests actually pass.

Phases follow the Section 14 roadmap. Two IDs are unassigned in the roadmap's
requirements column (a document gap): **EVL-1** is gap-filled in Phase 2 (the
N-repeat runner) and **AST-4** in Phase 6 (DLP scan of test assets).

| ID | Requirement | Phase | Status | Implementation | Tests |
|----|-------------|-------|--------|----------------|-------|
| GOV-1 | Humans define thresholds/taxonomies; no AI-only sign-off | 2 | satisfied | `framework/signoff.py` `framework/gate_runner.py` | `tests/l1_unit/test_thresholds_gates.py` |
| GOV-2 | Thresholds versioned per risk tier with the suite | 2 | satisfied | `framework/thresholds.py` `thresholds/critical.yaml` `thresholds/high.yaml` `thresholds/standard.yaml` | `tests/l1_unit/test_thresholds_gates.py` |
| GOV-3 | Test plans and evaluation dashboards published per release | 6 | satisfied | `telemetry/dashboard.py` `telemetry/metrics.py` `.github/workflows/nightly.yml` | `tests/l1_unit/test_phase6_units.py` `tests/l1_unit/test_ci_configs.py` |
| GOV-4 | Nightly regression on every active branch | 2 | satisfied | `.github/workflows/nightly.yml` `.github/workflows/pr-smoke.yml` `scripts/tasks.py` | `tests/l1_unit/test_ci_configs.py` |
| GOV-5 | Differential evaluation before model version change/swap | 6 | satisfied | `framework/diff_eval.py` | `tests/l1_unit/test_phase6_units.py` |
| AST-1 | Prompts/models/datasets/schemas versioned, linked to every run | 1 | satisfied | `framework/artifacts.py` `framework/runlog.py` `sut/prompts.py` | `tests/l1_unit/test_artifacts_runlog.py` `tests/l1_unit/test_agent.py` |
| AST-2 | Golden datasets per capability with owner and refresh cadence | 4 | satisfied | `datasets/registry.yaml` | `tests/l1_unit/test_synthetic.py` |
| AST-3 | Scale 1k -> 100k synthetic cases, dedup + human audit sample | 4 | satisfied | `synthetic/generator.py` `synthetic/dedup.py` `synthetic/audit.py` `synthetic/runner.py` `synthetic/scale_run.py` `.github/workflows/weekly-scale.yml` | `tests/l1_unit/test_synthetic.py` |
| AST-4 | Test data anonymized/synthetic; no secrets in prompts or logs | 6 | satisfied | `guardrails/dlp.py` `guardrails/scan.py` `.gitignore` | `tests/l8_security/test_guardrails_miss_fp.py` `tests/l8_security/test_injection_scans_soc2.py` |
| EVL-1 | N repeats per case; gates use pass rate with confidence interval | 2 | satisfied | `framework/repeat.py` `framework/statistics.py` `thresholds/critical.yaml` | `tests/l2_prompt/test_statistical.py` `tests/l1_unit/test_statistics.py` |
| EVL-2 | Temperature/structured-output/sanitization are versioned params | 1 | satisfied | `framework/config.py` `sut/sanitize.py` `sut/schemas.py` `.env.example` | `tests/l1_unit/test_config.py` `tests/l1_unit/test_sanitize.py` |
| EVL-3 | Four RAGAS metrics computed for every RAG release | 3 | satisfied | `evals/ragas_metrics.py` `datasets/rag/baseline.json` | `tests/l6_rag/test_ragas_metrics.py` |
| EVL-4 | LLM-judge calibrated against human labels (Spearman >= 0.8) | 4 | satisfied | `evals/judge.py` `evals/calibrate.py` `datasets/golden/judge_calibration.csv` | `tests/l5_llm_output/test_golden_and_judge.py` |
| EVL-5 | Baseline unit logic >= 85% branch coverage | 1 | satisfied | `pyproject.toml` | `tests/l1_unit/` |
| RAG-1 | Documents verified parsed/chunked/embedded/retrievable | 3 | satisfied | `sut/rag/verify_ingestion.py` `sut/rag/loader.py` `sut/rag/pdf_lite.py` | `tests/l4_retrieval/test_ingestion.py` |
| RAG-2 | Retrieval benchmarked by distance + top-k on labeled queries | 3 | satisfied | `sut/rag/benchmark.py` `datasets/retrieval/labeled_queries.csv` | `tests/l4_retrieval/test_benchmark.py` |
| AGT-1 | Hard call-stack recursion limit per session | 5 | satisfied | `breakers/monitor.py` `sut/agent_loop.py` | `tests/l7_agent/test_breakers.py` |
| AGT-2 | Deterministic breaker on identical repeated state | 5 | satisfied | `breakers/monitor.py` `sut/agent_loop.py` | `tests/l7_agent/test_breakers.py` |
| AGT-3 | Tool-input hash blocks duplicate identical calls | 5 | satisfied | `breakers/monitor.py` `sut/agent_loop.py` | `tests/l7_agent/test_breakers.py` `tests/l7_agent/test_agent_loop.py` |
| AGT-4 | Max step budget per request (e.g. 10) | 5 | satisfied | `breakers/monitor.py` `sut/agent_loop.py` | `tests/l7_agent/test_breakers.py` |
| AGT-5 | Missing/malformed input handled without looping | 5 | satisfied | `sut/agent_loop.py` `sut/policy.py` | `tests/l7_agent/test_agent_loop.py` |
| MCP-1 | Agents parse tool defs, call right API, process payloads | 5 | satisfied | `sut/mcp_server.py` `sut/tools/base.py` | `tests/l3_api/test_mcp_contract.py` |
| MCP-2 | Token consumption tracked per request and per tool | 5 | satisfied | `sut/agent_loop.py` TokenLedger | `tests/l7_agent/test_agent_loop.py` |
| SEC-1 | Direct+indirect prompt injection blocked and benchmarked | 6 | satisfied | `guardrails/injection.py` `guardrails/runtime.py` `guardrails/redteam.py` `promptfooconfig.yaml` | `tests/l8_security/test_guardrails_miss_fp.py` `tests/l8_security/test_injection_scans_soc2.py` |
| SEC-2 | Keys/private paths/open ports scanned and masked | 6 | satisfied | `guardrails/scan.py` `guardrails/infra_mask.py` | `tests/l8_security/test_injection_scans_soc2.py` `tests/l8_security/test_guardrails_miss_fp.py` |
| SEC-3 | RAG context and outputs filtered for PII/financial data | 6 | satisfied | `guardrails/dlp.py` | `tests/l8_security/test_guardrails_miss_fp.py` |
| SEC-4 | Toxicity/policy/brand checks before display | 6 | satisfied | `guardrails/brand.py` | `tests/l8_security/test_guardrails_miss_fp.py` |
| SEC-5 | SOC 2 Type 2 considerations mapped; evidence generated | 6 | satisfied | `evidence/soc2.py` | `tests/l8_security/test_injection_scans_soc2.py` |
| PRD-1 | Inline guardrails intercept live traffic | 6 | satisfied | `guardrails/runtime.py` `sut/api.py` | `tests/l9_e2e/test_http_journeys.py` `tests/l8_security/test_guardrails_miss_fp.py` |
| PRD-2 | Accuracy/Context Precision/latency streamed as telemetry | 6 | satisfied | `telemetry/metrics.py` `telemetry/drift.py` | `tests/l1_unit/test_phase6_units.py` |
| PRD-3 | Thumbs up-down and retries feed back into suites | 6 | satisfied | `framework/feedback.py` `datasets/feedback/feedback.csv` | `tests/l1_unit/test_phase6_units.py` |
