"""Canonical registry of the 31 requirements from blueprint Section 4.

Single source of truth shared by ``docs/traceability.md`` and the executable
traceability test (``tests/l1_unit/test_traceability.py``). The phase column
follows the Section 14 roadmap; EVL-1 and AST-4 are unassigned in the roadmap's
requirements column and are gap-filled in phases 2 and 6 respectively.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Requirement:
    id: str
    summary: str
    phase: int  # build phase (1..6) in which the requirement is satisfied


REQUIREMENTS: tuple[Requirement, ...] = (
    # Governance
    Requirement("GOV-1", "Humans define thresholds/taxonomies; no AI-only sign-off", 2),
    Requirement("GOV-2", "Thresholds versioned per risk tier with the suite", 2),
    Requirement("GOV-3", "Test plans and evaluation dashboards published per release", 6),
    Requirement("GOV-4", "Nightly regression on every active branch", 2),
    Requirement("GOV-5", "Differential evaluation before model version change/swap", 6),
    # Artifacts & data
    Requirement("AST-1", "Prompts/models/datasets/indexes/schemas versioned, linked to runs", 1),
    Requirement("AST-2", "Golden datasets per capability with owner and refresh cadence", 4),
    Requirement("AST-3", "Scale 1k -> 100k synthetic cases, dedup + human audit sample", 4),
    Requirement("AST-4", "Test data anonymized/synthetic; no secrets in prompts or logs", 6),
    # Evaluation
    Requirement("EVL-1", "N repeats per case; gates use pass rate with confidence interval", 2),
    Requirement("EVL-2", "Temperature/structured-output/sanitization are versioned params", 1),
    Requirement("EVL-3", "Four RAGAS metrics computed for every RAG release", 3),
    Requirement("EVL-4", "LLM-judge calibrated against human labels (Spearman >= 0.8)", 4),
    Requirement("EVL-5", "Baseline unit logic >= 85% branch coverage", 1),
    # Retrieval
    Requirement("RAG-1", "Documents verified parsed/chunked/embedded/retrievable", 3),
    Requirement("RAG-2", "Retrieval benchmarked by distance + top-k on labeled queries", 3),
    # Agentic
    Requirement("AGT-1", "Hard call-stack recursion limit per session", 5),
    Requirement("AGT-2", "Deterministic breaker on identical repeated state", 5),
    Requirement("AGT-3", "Tool-input hash blocks duplicate identical calls", 5),
    Requirement("AGT-4", "Max step budget per request (e.g. 10)", 5),
    Requirement("AGT-5", "Missing/malformed input handled without looping", 5),
    # MCP
    Requirement("MCP-1", "Agents parse tool defs, call right API, process payloads", 5),
    Requirement("MCP-2", "Token consumption tracked per request and per tool", 5),
    # Security
    Requirement("SEC-1", "Direct+indirect prompt injection blocked and benchmarked", 6),
    Requirement("SEC-2", "Keys/private paths/open ports scanned and masked", 6),
    Requirement("SEC-3", "RAG context and outputs filtered for PII/financial data", 6),
    Requirement("SEC-4", "Toxicity/policy/brand checks before display", 6),
    Requirement("SEC-5", "SOC 2 Type 2 considerations mapped; evidence generated", 6),
    # Production
    Requirement("PRD-1", "Inline guardrails intercept live traffic", 6),
    Requirement("PRD-2", "Accuracy/Context Precision/latency streamed as telemetry", 6),
    Requirement("PRD-3", "Thumbs up-down and retries feed back into suites", 6),
)

REQUIREMENT_IDS: frozenset[str] = frozenset(r.id for r in REQUIREMENTS)


def requirement_by_id(req_id: str) -> Requirement:
    """Look up a requirement by ID; KeyError for unknown IDs."""
    for req in REQUIREMENTS:
        if req.id == req_id:
            return req
    raise KeyError(req_id)


def requirements_for_phase(phase: int) -> list[Requirement]:
    """All requirements assigned to a build phase."""
    return [r for r in REQUIREMENTS if r.phase == phase]
