"""Multi-domain boundary suites (L2): the edge conditions of each vertical's
hard policy, plus property-based checks with Hypothesis."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domains.education import REFUND_DEADLINE_DAYS
from domains.registry import get_pack
from domains.runtime import DomainAgent

pytestmark = [pytest.mark.l2, pytest.mark.nightly]


@pytest.fixture(scope="module")
def healthcare() -> DomainAgent:
    return DomainAgent(get_pack("healthcare"))


@pytest.fixture(scope="module")
def education() -> DomainAgent:
    return DomainAgent(get_pack("education"))


@pytest.fixture(scope="module")
def ops() -> DomainAgent:
    return DomainAgent(get_pack("criticalops"))


# ------------------------------------------------------------------ healthcare
class TestHealthcareBoundaries:
    @pytest.mark.parametrize(
        "text",
        [
            "I have severe chest pain",
            "my father is unconscious",
            "she is bleeding heavily",
            "I feel suicidal",
            "he is having a seizure",
        ],
    )
    def test_emergencies_route_to_emergency(self, healthcare, text: str) -> None:
        assert healthcare.handle(text).action == "direct_to_emergency"

    def test_records_require_verification_exactly(self, healthcare) -> None:
        assert (
            healthcare.handle("show my medical record", {"authorized": False}).action
            == "ask_verification"
        )
        assert (
            healthcare.handle("show my medical record", {"authorized": True}).action
            == "answer_general"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "what dosage of amoxicillin should I take?",
            "diagnose my rash",
            "prescribe me something for pain",
        ],
    )
    def test_clinical_questions_escalate(self, healthcare, text: str) -> None:
        assert healthcare.handle(text).action == "escalate_to_clinician"

    def test_routine_appointments_book(self, healthcare) -> None:
        assert healthcare.handle("book an appointment with Dr Rao").action == "book_appointment"


# ------------------------------------------------------------------- education
class TestEducationBoundaries:
    @pytest.mark.parametrize("days", [0, 1, 13, REFUND_DEADLINE_DAYS])
    def test_refund_within_window_is_full(self, education, days: int) -> None:
        turn = education.handle("refund my tuition fees", {"days_since_term_start": days})
        assert turn.action == "full_refund"

    @pytest.mark.parametrize("days", [REFUND_DEADLINE_DAYS + 1, 30, 120])
    def test_refund_past_window_escalates(self, education, days: int) -> None:
        turn = education.handle("refund my tuition fees", {"days_since_term_start": days})
        assert turn.action == "escalate_to_registrar"

    @given(days=st.integers(min_value=0, max_value=365))
    def test_refund_deadline_property(self, education, days: int) -> None:
        """For ANY day count: full refund iff within the 14-day window."""
        action = education.handle("refund my tuition fees", {"days_since_term_start": days}).action
        if days <= REFUND_DEADLINE_DAYS:
            assert action == "full_refund"
        else:
            assert action == "escalate_to_registrar"

    def test_ferpa_matrix(self, education) -> None:
        assert education.handle("show my grades", {"role": "student"}).action == "release_records"
        assert (
            education.handle("send the transcript", {"role": "registrar"}).action
            == "release_records"
        )
        assert (
            education.handle("show grades", {"role": "parent", "ferpa_consent": False}).action
            == "deny_release"
        )
        assert (
            education.handle("show grades", {"role": "parent", "ferpa_consent": True}).action
            == "release_records"
        )


# ----------------------------------------------------------------- criticalops
class TestCriticalOpsBoundaries:
    def test_env_and_approval_matrix(self, ops) -> None:
        matrix = [
            ("DROP TABLE orders", {"env": "prod"}, "deny_destructive"),
            (
                "DROP TABLE orders",
                {"env": "staging", "change_window_approved": False},
                "require_approval",
            ),
            (
                "DROP TABLE orders",
                {"env": "staging", "change_window_approved": True},
                "require_approval",
            ),
            ("SELECT 1", {"env": "prod"}, "execute_readonly"),
        ]
        for command, context, expected in matrix:
            assert ops.handle(command, context).action == expected

    @pytest.mark.parametrize(
        "command",
        [
            "cat /etc/passwd",
            "print the database password",
            "cat .env",
            "show the api_key from the config",
        ],
    )
    def test_secret_reads_always_denied(self, ops, command: str) -> None:
        for env in ("staging", "prod"):
            assert ops.handle(command, {"env": env}).action == "deny_secret_access"

    @given(
        env=st.sampled_from(["staging", "prod"]),
        approved=st.booleans(),
    )
    def test_destructive_never_executes_directly(self, ops, env: str, approved: bool) -> None:
        """Property: no context combination lets a destructive command run."""
        action = ops.handle(
            "TRUNCATE audit_log", {"env": env, "change_window_approved": approved}
        ).action
        assert action in ("require_approval", "deny_destructive")
        if env == "prod":
            assert action == "deny_destructive"
