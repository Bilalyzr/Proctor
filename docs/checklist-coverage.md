# End-to-End Checklist Coverage

Maps every item of the end-to-end AI QA testing checklist (12 areas, ~70
items) to its status and evidence in this repository. A test
(`tests/l1_unit/test_checklist_coverage.py`) parses this file and fails on
malformed rows or unknown statuses - the map stays honest.

Statuses: `covered` (tests/artifacts exist), `partial` (core exists, depth
noted), `pending` (tracked in docs/TODO.md), `not-applicable` (SUT has no
such surface today, with the trigger that would make it applicable).

| Area | Item | Status | Evidence |
|------|------|--------|----------|
| Requirement & Risk Analysis | Define business requirements | covered | blueprint + `framework/requirements.py` (31 IDs) + `docs/traceability.md` |
| Requirement & Risk Analysis | Identify AI-specific risks | covered | risk tiers `thresholds/{critical,high,standard}.yaml`; adversarial suites L2/L8; per-pack `risk_note` |
| Requirement & Risk Analysis | Accuracy/latency/safety/reliability targets | covered | `thresholds/*.yaml` (pass rates, p95 SLA, zero-breach, CI gates) |
| Requirement & Risk Analysis | Compliance/privacy requirements | covered | SEC-2/3/5 suites; DLP; PHI/FERPA packs; `evidence/soc2.py` |
| Test Data Management | Training data validation | partial | SUT is API-driven (no training); dataset schema validation + registry exist; DVC-ready layout |
| Test Data Management | Test/validation dataset creation | covered | 29 golden/adversarial sets (28 packs + injection corpus), 64 labeled retrieval queries, 33-row judge calibration |
| Test Data Management | Data quality checks | covered | `synthetic/audit.py` (schema validation, dedup, audit sample) |
| Test Data Management | Data bias and imbalance detection | covered | counterfactual fairness suites + per-slice parity gate (`tests/l2_prompt/test_fairness.py`, `framework/statistics.slice_parity`) |
| Test Data Management | PII/privacy validation | covered | DLP suites (Luhn-gated PANs, PHI, student IDs), secret scans, AST-4 |
| Test Data Management | Synthetic test-data generation | covered | `synthetic/` pipeline (taxonomy -> generate -> dedup -> validate -> audit); 10k live demo |
| Model Testing | Functional testing | covered | L1 unit suites; 28 policy engines |
| Model Testing | Accuracy/precision/recall/F1 testing | covered | `framework/statistics.py` (confusion matrix, P/R/F1); classifier eval on labeled corpus (`tests/l1_unit/test_classifier_metrics.py`); Recall@k/MRR/nDCG (L4) |
| Model Testing | Regression testing | covered | baselines + no-drop gates (L6), prompt regression (L2), GOV-5 diff eval |
| Model Testing | Edge-case testing | covered | boundary/negative suites + Hypothesis properties |
| Model Testing | Robustness testing | covered | metamorphic/paraphrase, failure injection, N-repeat statistics |
| Model Testing | Bias/fairness testing | covered | name/religion counterfactual invariance across 8 packs |
| Model Testing | Explainability testing | covered | every decision carries a rationale; overrides self-identify ("Policy override") (`tests/domains/test_explainability.py`) |
| Model Testing | Model drift testing | covered | PSI drift bands (`telemetry/drift.py`) + behavioral diff (`framework/diff_eval.py`) |
| API & Backend Testing | REST/GraphQL API testing | partial | REST: FastAPI journeys + MCP JSON-RPC contracts; GraphQL: not-applicable until the SUT exposes a GraphQL endpoint |
| API & Backend Testing | Request/response validation | covered | Pydantic request models; 422 on oversized input |
| API & Backend Testing | Authentication/authorization | covered | X-API-Key auth (401s) + role gates in packs; `tests/l9_e2e/test_api_security.py` |
| API & Backend Testing | Error handling | covered | MCP error transport (-32700/-32601/-32602, isError), invalid-args suites |
| API & Backend Testing | Schema validation | covered | jsonschema on tool inputSchemas; Pydantic structured outputs |
| API & Backend Testing | Rate-limit testing | covered | token bucket, 429 + Retry-After + per-key isolation |
| API & Backend Testing | Contract testing | covered | MCP golden request/response fixtures per tool |
| AI/LLM-Specific Testing | Prompt testing | covered | L2 boundary/negative/breach + metamorphic suites |
| AI/LLM-Specific Testing | Prompt injection testing | covered | direct/indirect/base64 suites, N-repeat zero-success gate |
| AI/LLM-Specific Testing | Hallucination detection | covered | no-answer handling, off-label/decline suites, hallucination-resistance (L6) |
| AI/LLM-Specific Testing | Groundedness/factuality testing | covered | faithfulness metric + no-drop baseline (L6) |
| AI/LLM-Specific Testing | Toxicity/safety testing | covered | brand-safety lexicon in/outbound, miss+FP suites |
| AI/LLM-Specific Testing | Jailbreak testing | covered | DAN/roleplay/override/multilingual suites + red-team taxonomy |
| AI/LLM-Specific Testing | Context-window testing | covered | size-boundary truncation + decision correctness + bounded multi-turn (`tests/l5_llm_output/test_context_window.py`) |
| AI/LLM-Specific Testing | Output consistency testing | covered | N-repeat consistency + 100% schema-validity gates (L5) |
| AI/LLM-Specific Testing | RAG retrieval testing | covered | ingestion verification, Recall@5/MRR/nDCG vs gate (L4) |
| AI/LLM-Specific Testing | RAG answer-quality testing | covered | four RAGAS-style metrics vs baseline (L6) |
| AI/LLM-Specific Testing | Tool/function-calling testing | covered | tool selection, args validation, trajectories, breakers (L7/L3) |
| UI/E2E Testing | User workflow testing | covered | multi-step HTTP journeys; browser journeys ready (P3) |
| UI/E2E Testing | Cross-browser testing | pending | journeys parametrized chromium/firefox/webkit; runs once browsers installed (docs/TODO.md P3) |
| UI/E2E Testing | Mobile/responsive testing | partial | viewport meta + fluid layout + static checks; device emulation in P3 |
| UI/E2E Testing | AI response rendering | covered | chat DOM renders replies via textContent (no HTML injection); browser assertions ready (P3) |
| UI/E2E Testing | File/image upload testing | not-applicable | SUT has no upload surface; add contract+size/type suites when it does |
| UI/E2E Testing | Chat/conversation flow testing | covered | multi-turn journey (ask -> provide order -> approve) |
| UI/E2E Testing | Accessibility testing | partial | lang, aria-live, labeled inputs, heading structure; full axe audit in P3 |
| Performance Testing | Response-time testing | covered | p95 latency assertions (L3, L9 load) vs thresholds |
| Performance Testing | Load testing | covered | async concurrent load harness: 25 workers x 8 reqs, all-200 + throughput gate (`tests/l9_e2e/test_load.py`) |
| Performance Testing | Stress testing | covered | oversized-payload stress case + agent step-budget breakers |
| Performance Testing | Concurrency testing | covered | asyncio.gather workers through ASGI transport; sharded runner concurrency |
| Performance Testing | Token/compute usage | covered | per-request/per-tool token ledger + cost tracking (MCP-2) |
| Performance Testing | Throughput testing | covered | requests-per-second measured and gated under load |
| Performance Testing | Scalability testing | covered | 10k-case sharded run (3.5s), 290k-case capacity, weekly-scale workflow |
| Security Testing | Authentication & authorization | covered | 401/200 auth suite + FERPA/HR/IAM role gates across packs |
| Security Testing | Prompt injection | covered | L8 suites + domain injection rules (HIPAA/FERPA/approval-forgery...) |
| Security Testing | Data leakage | covered | DLP on RAG context + outputs; PHI/student-ID masking |
| Security Testing | Sensitive-information disclosure | covered | seeded-secret tests; infra masking (keys/paths/ports) |
| Security Testing | Adversarial input testing | covered | adversarial suites, malformed payloads, invalid tool args |
| Security Testing | API security | covered | auth + rate limiting + schema bounds; hardened Docker (non-root) |
| Security Testing | Dependency/security scanning | partial | repo secret scanner (enforced) + pip-audit in CI (report-only until baselined; docs/TODO.md) |
| Evaluation & Quality Gates | Automated evaluation | covered | every layer has executable gates from thresholds/ |
| Evaluation & Quality Gates | Human evaluation | covered | GOV-1 sign-off records, audit samples, human labels |
| Evaluation & Quality Gates | Golden datasets | covered | 40 golden sets, registered with owners + refresh cadence |
| Evaluation & Quality Gates | LLM-as-a-judge evaluation | covered | MockJudge + Spearman calibration >= 0.8 (EVL-4) |
| Evaluation & Quality Gates | Quality thresholds | covered | versioned per risk tier, digest-linked to runs |
| Evaluation & Quality Gates | Regression comparison | covered | baselines, no-drop gates, differential eval reports |
| Evaluation & Quality Gates | Release acceptance criteria | covered | gate chain + `--release` sign-off requirement + exit criteria |
| CI/CD & Automation | Automated test execution | covered | pr-smoke / nightly / weekly-scale workflows |
| CI/CD & Automation | Unit->API->AI eval->E2E pipeline | covered | gate chain climbs L1..L9, failure stops promotion |
| CI/CD & Automation | Regression suites | covered | nightly full regression + statistical gates |
| CI/CD & Automation | Test reports | covered | JSONL run logs, manifests, HTML dashboard, coverage reports |
| CI/CD & Automation | Quality gates | covered | `make gate` / `framework.gate_runner` |
| CI/CD & Automation | Deployment validation | covered | Dockerfile (non-root, HEALTHCHECK /health), compose healthcheck, CI docker build + compose config check |
| Production Monitoring | Accuracy/quality monitoring | covered | gauges + drift bands in `telemetry/`; dashboard spec |
| Production Monitoring | Latency monitoring | covered | p95 gauge + latency gates |
| Production Monitoring | Error monitoring | partial | error counts in run logs + verdicts; alerting hooks in dashboard |
| Production Monitoring | Hallucination monitoring | partial | faithfulness metrics per release; PSI alerting on metric decay |
| Production Monitoring | Drift detection | covered | PSI bands (stable/investigate/alert) |
| Production Monitoring | Cost/token monitoring | covered | token ledger + price table + cost-per-run reports |
| Production Monitoring | User feedback monitoring | covered | thumbs/retry ingestion + weekly triage (PRD-3) |
| Continuous Improvement | Production issue analysis | covered | feedback-to-test pipeline with cluster triage |
| Continuous Improvement | New test-case generation | covered | synthetic generator + feedback promotion |
| Continuous Improvement | Dataset updates | covered | registry refresh cadences + versioned baselines |
| Continuous Improvement | Prompt/model improvements | partial | framework evaluates prompts/models (regression, diff eval); authoring improvements stays human |
| Continuous Improvement | Regression test updates | covered | feedback cases append to golden sets automatically |
| Continuous Improvement | Periodic AI risk assessment | covered | nightly regression, weekly scale run, weekly feedback triage, evidence pack regeneration |
