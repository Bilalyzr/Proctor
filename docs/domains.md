# Multi-Domain Testing (Domain Packs)

The pyramid harness is domain-agnostic infrastructure; each *industry
vertical* plugs in as a **domain pack**. One command runs every vertical's
golden set through the same agent pipeline, gates, guardrails and statistics:

```bash
python -m domains     # or: .venv/bin/python -m domains
```

## The 28 domain packs (16 industry groups)

Four **hand-crafted packs** (deep, bespoke policies + tools + guardrails) and
twelve **catalog packs** (declarative `PackSpec`: ordered rules + hard
invariants, compiled by `domains/catalog.py` into the same interface).

| # | Vertical | Pack | Hard policy under test | Golden |
|---|----------|------|------------------------|--------|
| 1 | Retail / E-commerce | `ecommerce` ★ | Refund cap: never approve above Rs 500 per order (single + cumulative) | 40 |
| 2 | Healthcare | `healthcare` ★ | PHI gate (no records without verified authorization), no dosage/diagnosis advice, emergency routing | 14 |
| 3 | Education | `education` ★ | FERPA-style records release, 14-day tuition-refund deadline, no grade tampering | 13 |
| 4 | Technology / DevOps | `criticalops` ★ | Destructive commands never in prod / never without an approved change window; secret reads denied | 17 |
| 5 | Finance (BFSI, fintech, insurance) | `finance` | Step-up auth for transfers ≥ Rs 10,000; daily limit Rs 10,00,000; no investment advice without compliance | 12 |
| 6 | Travel (airlines, hotels, booking) | `travel` | Free cancellation only 24+ h before departure; no-shows denied; no upgrade promises | 11 |
| 7 | Transportation (cab, logistics, fleet) | `transportation` | Undeclared hazardous goods never ship; post-assignment ride cancellation fees | 10 |
| 8 | Automotive (connected cars, EV) | `automotive` | Speed-limit overrides always denied; firmware only parked + owner-verified | 10 |
| 9 | Enterprise (ERP, CRM, HRMS, SaaS) | `enterprise` | Discounts > 10% need manager approval; payroll is HR-only; POs > Rs 50k need approval | 10 |
| 10 | Communication (telecom, messaging) | `communication` | SIM swaps always fraud-checked; port-outs need OTP; no bulk SMS to DND numbers | 10 |
| 11 | Media (OTT, streaming, gaming) | `media` | Refunds only ≤ 7 days AND < 2 h watched; parent PIN on minor purchases; adult content blocked for minors | 10 |
| 12 | Government (citizen, tax, identity) | `government` | Identity docs masked + verification-gated; tax-evasion assistance denied | 10 |
| 13 | Manufacturing (MES, PLM, IoT) | `manufacturing` | Safety-interlock bypasses denied; speed changes > 10% need supervisor; failed-QC batches held | 10 |
| 14 | Energy (utilities, oil & gas) | `energy` | Gas leaks always emergency-routed; feeder shutdowns need permits; meter data needs consent | 10 |
| 15 | Real Estate (property, construction) | `realestate` | Deposits capped at 2 months' rent; unpermitted structural work denied | 10 |
| 16 | Life Sciences (pharma, biotech, devices) | `lifesciences` | Adverse events ALWAYS escalated to pharmacovigilance; off-label advice denied; trial data authorized | 10 |

★ hand-crafted pack — includes MCP tools, agent-loop integration and
guardrule/PHI/FERPA extension suites in `tests/domains/`.

## The 80 application-domain catalog

Beyond the 16 industry groups, `domains/appdomains.py` initializes the full
master list of **80 application domains** (banking, insurance, fintech,
healthcare, pharma, e-commerce, travel, hospitality, airlines, automotive,
manufacturing, telecom, media, gaming, education, government, real estate,
construction, energy, oil & gas, logistics, transportation, food tech,
agritech, legaltech, HRtech, CRM, ERP, SaaS, MarTech, AdTech, cybersecurity,
cloud, DevOps, social, collaboration, healthcare insurance, fitness, sports,
pharmacy e-commerce, delivery apps, ride-hailing, EV, smart home, IoT,
blockchain, crypto, AI/ML apps, robotics, AR/VR, smart cities, climate tech,
airport management, maritime, defense, biotech, medical devices, procurement,
wholesale, fashion, OTT, news, CMS, document management, productivity,
project management, accounting, payroll, POS, helpdesk, IAM, BI, data
engineering, scientific software, collaboration, subscriptions,
marketplaces, booking, digital identity/KYC, and taxation).

Twelve extension packs (`domains/verticals_ext.py`) absorb the domains that
sit outside the original 16 groups: `foodtech`, `agritech`, `legaltech`,
`martech` (Mar/AdTech), `social`, `wellness` (fitness/sports), `web3`
(blockchain/crypto), `aerospace` (defense), `productivity` (CMS/docs/apps/
projects), `dataai` (data/BI/AI), `support`, `iot_robotics` (smart
home/IoT/robotics) - bringing the matrix to **28 packs**.

Every one of the 80 domains carries an **executable probe**
(`tests/domains/test_appdomains.py`): its scenario runs through the pack's
agent and must land on the policy-correct action. "All 80 initialized" is a
test-enforced statement, not a claim.

## What every pack guarantees (the generality proof)

For **every** vertical, `tests/domains/test_catalog.py` proves:

1. **Golden set passes** through the generic DomainAgent (matrix, ≥ 90%).
2. **Rogue model is corrected**: a model scripted to violate the vertical's
   #1 hard policy (leak records, execute the transfer, ship the hazmat, deny
   nothing) is overridden by the code-side guard — `policy_blocked = True`.
3. **Compliant persona passes freely** — the guard has no false positives on
   benign traffic.
4. Schema compilation, action-space validation, and golden-file shape.

## What a pack contains

Hand-crafted packs (`domains/<id>.py`): facts parser + policy engine
(`parse`/`evaluate`/`enforce`), decision schema, persona prompt + hints,
guardrail extensions (injection rules, DLP patterns), golden set, and where
relevant MCP tools.

Catalog packs (`domains/verticals.py`): a `PackSpec` — fact extractors,
ordered `Rule`s (first match decides), hard `Invariant`s (the post-model
guard), a rogue-model `probe`, prompt and optional DLP/injection extensions —
compiled into the identical `DomainPack` interface.

## How packs ride the pyramid

Domain suites live in `tests/domains/` and are selected by the standard layer
markers, so they run inside the existing gates: boundary/property tests →
`@pytest.mark.l2`, agent defense-in-depth → `l7`, guardrails/security → `l8`.
The matrix (`python -m domains`) aggregates per-pack pass rates with Wilson
confidence intervals into `reports/domain_matrix.json` (nightly artifact).

## Adding vertical #17

1. Add a `PackSpec` to `domains/verticals.py` (extract + rules + invariants +
   probe) — `ENTERPRISE` is a compact template.
2. Register it in `ALL_VERTICAL_SPECS`.
3. Add `datasets/domains/<id>_golden.csv` (≥ 10 cases) and register it in
   `datasets/registry.yaml`.
4. The matrix, the generic rogue-model test, the gates and CI pick it up
   automatically — no harness changes needed.
