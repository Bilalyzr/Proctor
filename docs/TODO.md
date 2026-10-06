# Pending Work

Deferred items from the post-build limitations review - accepted, tracked,
and **not silently forgotten**. Each entry says exactly what closes it.

## P1 — Real-model validation run  *(blocked on: provider API key)*

The MOCK provider validates the harness; real-model numbers need a real
provider. No code changes required - the path is already built and tested:

```bash
cp .env.example .env
# edit .env: AIQA_PROVIDER=gemini + AIQA_GEMINI_API_KEY=...  (or anthropic/openai)
python scripts/tasks.py test      # full suite against the real model
python scripts/tasks.py gate     # all nine gates with real-model numbers
python -m domains                # 28-pack matrix, real-model pass rates
```

Deliverables when done: real-model golden-slice accuracy (the >90% target,
currently provable only offline), real four-metric RAG scores vs
`datasets/rag/baseline.json`, and a GOV-5 differential report
(`python -m framework.diff_eval` config A/B) for any future model swap.
Cost guardrail: start with a small N (AIQA_REPEAT_RUNS=5) before nightly.

## P2 — Heavy-engine integration pass  *(optional)*

Install the optional extras and run once where a real provider applies;
CI stays offline-first (fallbacks remain the default):

```bash
pip install 'proctor[ragas]' 'proctor[presidio]' \
            'proctor[faiss]'
# garak / pyrit via their own channels; promptfoo via npm
```

Verify each adapter activates (report engine names change from
`local-reference-v1` / `regex-dlp-v1` etc. to the real engines) and that
the offline suites still pass unchanged.

## P3 — Enable Playwright browser journeys  *(closable anytime, ~5 min)*

The two skipped tests in `tests/l9_e2e/test_browser_journeys.py` carry the
real browser E2E; HTTP journeys hold the L9 gate meanwhile:

```bash
pip install 'proctor[playwright]'
playwright install chromium
python -m pytest tests/l9_e2e -m l9          # 0 skips expected
```

Then add a `playwright install chromium --with-deps` step to
`.github/workflows/pr-smoke.yml` (and nightly) so CI runs them too.

## P4 — CI hygiene  *(nice-to-have)*

- Bump `actions/checkout@v4` / `setup-python@v5` / `upload-artifact@v4` to
  the newest majors (silences Node-20 deprecation annotations).
- Pin or migrate the `ubuntu-latest` image (migration notice effective
  2026-10-19).
- Confirm `nightly` and `weekly-scale` workflows on their first scheduled
  triggers (both are green on manual/log-verified runs so far).

## Never-Do (by design, not pending work)

- **SOC 2 Type 2 stays evidence-only.** Compliance is certified by an
  external auditor over time, never by this repository
  (`evidence/soc2.py` enforces the disclaimer; tests assert it). Do not
  "resolve" this - a compliance claim would be false.
- **Offline-first stays the default.** CI runs keyless on the MOCK
  provider by design; real providers activate only via environment
  variables.
