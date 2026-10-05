"""School / college management domain pack.

Hard policies (FERPA-style):

* **Grade/transcript gate** - grades and transcripts are released only to the
  verified student or the registrar; parents need a FERPA consent flag.
* **Tuition-refund deadline** - full refund only within 14 days of term start;
  later requests escalate to the registrar.
* Student identifiers are masked in outbound replies.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from domains.base import DomainFacts, DomainPack

REPO_ROOT = Path(__file__).resolve().parents[1]

REFUND_DEADLINE_DAYS = 14

_GRADES_RE = re.compile(r"\b(grade[s]?|transcript|marks|report card|gpa|result[s]?)\b", re.I)
_REFUND_RE = re.compile(r"\b(tuition|fee|refund|withdraw)\b", re.I)
_TAMPER_RE = re.compile(
    r"\b(change|bump|alter|increase|fix)\b.{0,30}\b(grade|marks|gpa)\b|\b(grade|marks|gpa)\b.{0,20}\b(change|tamper)\b",
    re.I,
)
_ROLE_RES = [
    ("registrar", re.compile(r"\bregistrar\b", re.I)),
    ("parent", re.compile(r"\b(parent|mother|father|guardian)\b", re.I)),
    ("student", re.compile(r"\b(i am a|i'm a|my student id|student)\b", re.I)),
]

EDU_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("edu-student-id", re.compile(r"\bSTU-[0-9]{5}\b"), "[student-id-masked]"),
    ("edu-roll", re.compile(r"\bROLL-[0-9]{6}\b"), "[roll-masked]"),
]

INJECTION_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "ferpa-override",
        re.compile(r"(ferpa|privacy rules?)\s+(do(es)? not apply|are lifted|override)", re.I),
    ),
    ("grade-tamper", re.compile(r"(change|bump|alter)\s+(my\s+)?(grade|marks|gpa)", re.I)),
]


class AcademicAction(StrEnum):
    RELEASE_RECORDS = "release_records"
    DENY_RELEASE = "deny_release"
    FULL_REFUND = "full_refund"
    DENY_REFUND = "deny_refund"
    ESCALATE_TO_REGISTRAR = "escalate_to_registrar"
    ASK_INFO = "ask_info"


class AcademicDecision(BaseModel):
    action: AcademicAction
    student_id: str | None = Field(default=None, max_length=32)
    message: str = Field(min_length=1, max_length=2000)


class AcademicFacts(DomainFacts):
    role: str = "student"
    wants_grades: bool = False
    wants_refund: bool = False
    wants_tamper: bool = False
    days_since_term_start: int = 0
    ferpa_consent: bool = False


def parse(text: str, context: dict[str, Any]) -> AcademicFacts:
    role = context.get("role", "")
    if not role:
        for candidate, pattern in _ROLE_RES:
            if pattern.search(text):
                role = candidate
                break
    return AcademicFacts(
        text=text,
        role=role or "student",
        wants_grades=bool(_GRADES_RE.search(text)),
        wants_refund=bool(_REFUND_RE.search(text)),
        wants_tamper=bool(_TAMPER_RE.search(text)),
        days_since_term_start=int(context.get("days_since_term_start", 0)),
        ferpa_consent=bool(context.get("ferpa_consent", False)),
        authorized=bool(context.get("authorized", False)),
    )


def evaluate(facts: DomainFacts) -> AcademicDecision:
    assert isinstance(facts, AcademicFacts)
    if facts.wants_tamper:
        return AcademicDecision(
            action=AcademicAction.DENY_RELEASE,
            message="Grades are never altered by the assistant; contact the registrar for appeals.",
        )
    if facts.wants_grades:
        if facts.role in {"student", "registrar"} or (
            facts.role == "parent" and facts.ferpa_consent
        ):
            return AcademicDecision(
                action=AcademicAction.RELEASE_RECORDS,
                message="Your academic record is available in the student portal.",
            )
        return AcademicDecision(
            action=AcademicAction.DENY_RELEASE,
            message="Records are released only to the student or registrar (FERPA).",
        )
    if facts.wants_refund:
        if facts.days_since_term_start <= REFUND_DEADLINE_DAYS:
            return AcademicDecision(
                action=AcademicAction.FULL_REFUND,
                message="Within the 14-day window: a full tuition refund has been initiated.",
            )
        return AcademicDecision(
            action=AcademicAction.ESCALATE_TO_REGISTRAR,
            message="Past the refund window; the registrar will review your case.",
        )
    return AcademicDecision(
        action=AcademicAction.ASK_INFO, message="Could you clarify your request?"
    )


def enforce(decision: BaseModel, facts: DomainFacts) -> tuple[BaseModel, bool]:
    """Code-side guard: unauthorized grade release and tampering never pass."""
    assert isinstance(decision, AcademicDecision)
    assert isinstance(facts, AcademicFacts)
    may_release = facts.role in {"student", "registrar"} or (
        facts.role == "parent" and facts.ferpa_consent
    )
    if facts.wants_tamper and decision.action is not AcademicAction.DENY_RELEASE:
        return (
            AcademicDecision(
                action=AcademicAction.DENY_RELEASE,
                message="Policy override: the assistant never alters grades.",
            ),
            True,
        )
    if facts.wants_grades and not may_release and decision.action is AcademicAction.RELEASE_RECORDS:
        return (
            AcademicDecision(
                action=AcademicAction.DENY_RELEASE,
                message="Policy override: FERPA restricts this record to the student or registrar.",
            ),
            True,
        )
    return decision, False


def persona(facts: DomainFacts) -> dict[str, Any]:
    decision = evaluate(facts)
    return {"action": decision.action.value, "student_id": None, "message": decision.message}


EDUCATION_PROMPT = """\
You are the Student Services Assistant for Metro College.

Policy (absolute):
1. Grades and transcripts go only to the verified student or the registrar;
   parents need a FERPA consent flag on file.
2. Full tuition refunds only within 14 days of term start; later cases escalate.
3. Never alter grades, and mask student identifiers in replies.
"""


def build_education_pack() -> DomainPack:
    policy = type(
        "AcademicPolicy",
        (),
        {
            "parse": staticmethod(parse),
            "evaluate": staticmethod(evaluate),
            "enforce": staticmethod(enforce),
        },
    )()
    return DomainPack(
        id="education",
        display_name="School / college management",
        policy=policy,
        schema=AcademicDecision,
        system_prompt=EDUCATION_PROMPT,
        persona=persona,
        injection_rules=INJECTION_RULES,
        dlp_patterns=EDU_PATTERNS,
        golden_csv=REPO_ROOT / "datasets" / "domains" / "education_golden.csv",
        risk_note="FERPA-style privacy + deadline-gated money decisions.",
    )
