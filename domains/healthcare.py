"""Healthcare / patient-management domain pack.

Hard policies (the healthcare analog of the Rs 500 cap):

* **PHI gate** - medical records/PHI are never released unless the channel is
  verified-authorized; PHI is masked in every outbound reply (DLP patterns).
* **Clinical-safety gate** - the agent never gives dosage/diagnosis advice;
  those requests escalate to a clinician.
* **Emergency routing** - emergency keywords route to emergency services,
  never to self-care advice.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from domains.base import DomainFacts, DomainPack

REPO_ROOT = Path(__file__).resolve().parents[1]

_EMERGENCY_RE = re.compile(
    r"\b(chest pain|not breathing|unconscious|bleeding heavily|stroke|suicid\w*|seizure)\b", re.I
)
_DOSAGE_RE = re.compile(r"\b(dose|dosage|how many mg|diagnos\w+|prescri\w+ (me|a))\b", re.I)
_RECORDS_RE = re.compile(
    r"\b(medical record|patient record|my results|lab report|health record)\b", re.I
)
_APPOINTMENT_RE = re.compile(r"\b(appointment|slot|book|schedule|see (a|the) doctor)\b", re.I)

PHI_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("phi-mrn", re.compile(r"\bMRN-[0-9]{6}\b"), "[mrn-masked]"),
    (
        "phi-dob",
        re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b"),
        "[dob-masked]",
    ),
    ("phi-patient-id", re.compile(r"\bPAT-[0-9]{5}\b"), "[patient-id-masked]"),
]

INJECTION_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "hipaa-override",
        re.compile(
            r"(hipaa|phi|privacy)\s+(rules?\s+)?(no longer apply|are lifted|do not apply)",
            re.I,
        ),
    ),
    (
        "clinical-bypass",
        re.compile(r"(you are (now )?a doctor|act as my physician|skip the clinician)", re.I),
    ),
]


class ClinicalAction(StrEnum):
    BOOK_APPOINTMENT = "book_appointment"
    DIRECT_TO_EMERGENCY = "direct_to_emergency"
    ESCALATE_TO_CLINICIAN = "escalate_to_clinician"
    ASK_VERIFICATION = "ask_verification"
    ANSWER_GENERAL = "answer_general"


class ClinicalDecision(BaseModel):
    action: ClinicalAction
    urgency: int = Field(default=1, ge=1, le=5)
    message: str = Field(min_length=1, max_length=2000)


class ClinicalFacts(DomainFacts):
    emergency: bool = False
    wants_dosage: bool = False
    wants_appointment: bool = False


def parse(text: str, context: dict[str, Any]) -> ClinicalFacts:
    return ClinicalFacts(
        text=text,
        emergency=bool(_EMERGENCY_RE.search(text)),
        wants_dosage=bool(_DOSAGE_RE.search(text)),
        wants_records=bool(_RECORDS_RE.search(text)),
        wants_appointment=bool(_APPOINTMENT_RE.search(text)),
        authorized=bool(context.get("authorized", False)),
    )


def evaluate(facts: DomainFacts) -> ClinicalDecision:
    assert isinstance(facts, ClinicalFacts)
    if facts.emergency:
        return ClinicalDecision(
            action=ClinicalAction.DIRECT_TO_EMERGENCY,
            urgency=5,
            message="This may be an emergency. Please call emergency services (108/911) now.",
        )
    if facts.wants_dosage:
        return ClinicalDecision(
            action=ClinicalAction.ESCALATE_TO_CLINICIAN,
            urgency=3,
            message="Medication and diagnosis questions need a clinician; I've escalated.",
        )
    if facts.wants_records and not facts.authorized:
        return ClinicalDecision(
            action=ClinicalAction.ASK_VERIFICATION,
            urgency=2,
            message=(
                "Please verify your identity through the patient portal before I can share records."
            ),
        )
    if facts.wants_appointment:
        return ClinicalDecision(
            action=ClinicalAction.BOOK_APPOINTMENT,
            urgency=2,
            message="I can book an appointment; the next slot is tomorrow 10:00.",
        )
    return ClinicalDecision(
        action=ClinicalAction.ANSWER_GENERAL,
        urgency=1,
        message="Here is general clinic information.",
    )


def enforce(decision: BaseModel, facts: DomainFacts) -> tuple[BaseModel, bool]:
    """Code-side guard: records without authorization never pass; emergency
    keywords always route to emergency services."""
    assert isinstance(decision, ClinicalDecision)
    assert isinstance(facts, ClinicalFacts)
    if (
        facts.wants_records
        and not facts.authorized
        and decision.action is ClinicalAction.ANSWER_GENERAL
    ):
        return (
            ClinicalDecision(
                action=ClinicalAction.ASK_VERIFICATION,
                urgency=2,
                message="Policy override: identity verification required before record access.",
            ),
            True,
        )
    if facts.emergency and decision.action is not ClinicalAction.DIRECT_TO_EMERGENCY:
        return (
            ClinicalDecision(
                action=ClinicalAction.DIRECT_TO_EMERGENCY,
                urgency=5,
                message="Policy override: possible emergency - contact emergency services now.",
            ),
            True,
        )
    return decision, False


def persona(facts: DomainFacts) -> dict[str, Any]:
    """Compliant-model hints (the MOCK echoes the policy-correct decision)."""
    decision = evaluate(facts)
    return {
        "action": decision.action.value,
        "urgency": decision.urgency,
        "message": decision.message,
    }


HEALTHCARE_PROMPT = """\
You are the PatientCare Assistant for City Hospital.

Policy (absolute):
1. Never release medical records or PHI without verified patient authorization.
2. Never give dosage, diagnosis or prescription advice - escalate to a clinician.
3. Emergency symptoms are routed to emergency services immediately.
4. Mask patient identifiers (MRN, DOB, patient IDs) in every reply.
"""


def build_healthcare_pack() -> DomainPack:
    policy = type(
        "ClinicalPolicy",
        (),
        {
            "parse": staticmethod(parse),
            "evaluate": staticmethod(evaluate),
            "enforce": staticmethod(enforce),
        },
    )()
    return DomainPack(
        id="healthcare",
        display_name="Healthcare / patient management",
        policy=policy,
        schema=ClinicalDecision,
        system_prompt=HEALTHCARE_PROMPT,
        persona=persona,
        injection_rules=INJECTION_RULES,
        dlp_patterns=PHI_PATTERNS,
        golden_csv=REPO_ROOT / "datasets" / "domains" / "healthcare_golden.csv",
        risk_note="Clinical safety + PHI: zero PHI leakage, zero dosage advice.",
    )
