# Multi-Domain Testing (Domain Packs)

The pyramid harness is domain-agnostic infrastructure; each *vertical* plugs
in as a **domain pack**. One command runs every domain's golden set through
the same agent pipeline, gates, guardrails and statistics:

```bash
python -m domains     # or: .venv/bin/python -m domains
```

| Pack | Vertical | Hard policy (the "Rs 500 cap" equivalent) | Golden set |
|------|----------|------------------------------------------|------------|
| `ecommerce` | E-commerce | Refund cap: never approve above Rs 500 per order (single + cumulative) | 40 cases |
| `healthcare` | Hospital / patient management | PHI gate (no records without verified authorization), clinical-safety gate (no dosage/diagnosis advice), emergency routing | 14 cases |
| `education` | School / college management | FERPA-style grade/transcript release (student/registrar/consented parent only), 14-day tuition-refund deadline, no grade tampering | 13 cases |
| `criticalops` | Critical tools / ops | Destructive-command gate (never in prod, never without an approved change window), secret-exfiltration gate | 17 cases |

## What a pack contains

Each pack (`domains/<id>.py`) bundles the vertical's entire test surface:

- **Facts parser + policy engine** - `parse(text, context) -> facts`,
  `evaluate(facts) -> decision`, and `enforce(decision, facts)` (the
  code-side guard: even a rogue model cannot produce a policy-violating
  decision - tested with scripted rogue models per domain).
- **Decision schema** - a Pydantic structured-output contract, so the
  provider-agnostic client, L5 output checks and the mock's schema
  synthesis all work unchanged.
- **Persona hints** - the deterministic MOCK acts as a compliant model for
  the vertical; non-compliance is injected via `MockStep` scripts.
- **Guardrail extensions** - domain injection rules (HIPAA-override,
  FERPA-override, approval-forgery, sudo-bypass) and DLP patterns
  (MRN/DOB/patient IDs, student/roll numbers) that extend the shared
  guardrail runtime.
- **Golden set** - boundary/negative/injection cases in
  `datasets/domains/<id>_golden.csv`, registered in `datasets/registry.yaml`
  with an owner and refresh cadence (AST-2).

## How packs ride the pyramid

Domain suites live in `tests/domains/` and are selected by the standard layer
markers, so they run inside the existing gates:

- boundary/property tests -> `@pytest.mark.l2` (gate: pass rate, zero breaches)
- agent defense-in-depth + guardrail wiring -> `@pytest.mark.l7` / `l8`
- the matrix (`python -m domains`) aggregates per-pack pass rates with Wilson
  confidence intervals into `reports/domain_matrix.json` (nightly artifact).

## Adding a new vertical

1. Create `domains/<id>.py` with facts/policy/schema/persona (+ optional
   guardrail extensions) - `domains/education.py` is a compact template.
2. Add the builder to `domains/registry.py::list_packs`.
3. Add `datasets/domains/<id>_golden.csv` and register it in
   `datasets/registry.yaml`.
4. Add boundary tests in `tests/domains/test_domain_boundaries.py` - the
   matrix, gates and CI pick everything up automatically.
