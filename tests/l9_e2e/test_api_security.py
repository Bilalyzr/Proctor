"""API security (checklist: authentication, rate-limit testing):
401 on missing/wrong key, 200 on the right key, 429 with Retry-After once
the token bucket empties, and per-key bucket isolation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sut.api import TokenBucket, create_app

pytestmark = [pytest.mark.l9, pytest.mark.nightly]

TEST_API_KEY = "test-api-key-123"  # test fixture value, not a credential


@pytest.fixture()
def secured() -> TestClient:
    return TestClient(create_app(api_key=TEST_API_KEY, rate_limit=(5, 0.001)))


class TestAuthentication:
    def test_missing_key_is_401(self, secured: TestClient) -> None:
        response = secured.post("/chat", json={"message": "hello"})
        assert response.status_code == 401
        assert "API key" in response.json()["detail"]

    def test_wrong_key_is_401(self, secured: TestClient) -> None:
        response = secured.post("/chat", json={"message": "hello"}, headers={"X-API-Key": "nope"})
        assert response.status_code == 401

    def test_correct_key_is_200(self, secured: TestClient) -> None:
        response = secured.post(
            "/chat",
            json={"message": "refund Rs 300 for the broken mug", "order_id": "ORD-1001"},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "approve"

    def test_health_reports_auth_posture(self, secured: TestClient) -> None:
        # /health is intentionally auth-exempt (container healthchecks)
        body = secured.get("/health").json()
        assert body["auth"] is True and body["rate_limited"] is True

        from sut.api import app as default_app

        assert TestClient(default_app).get("/health").json()["auth"] is False

    def test_keyless_default_app_stays_open(self) -> None:
        client = TestClient(create_app(api_key=None, rate_limit=None))
        assert client.post("/chat", json={"message": "hello"}).status_code == 200


class TestRateLimiting:
    def test_429_after_burst_with_retry_after(self, secured: TestClient) -> None:
        headers = {"X-API-Key": TEST_API_KEY}
        statuses = []
        for _ in range(10):
            response = secured.post("/chat", json={"message": "hi"}, headers=headers)
            statuses.append(response.status_code)
        assert 200 in statuses and 429 in statuses
        # the limiter returns a Retry-After header (politeness contract)
        response = secured.post("/chat", json={"message": "hi"}, headers=headers)
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert float(response.headers["Retry-After"]) >= 0.0

    def test_buckets_are_per_key(self, secured: TestClient) -> None:
        """Exhausting one key does not rate-limit another client."""
        for _ in range(10):
            secured.post("/chat", json={"message": "hi"}, headers={"X-API-Key": TEST_API_KEY})
        other = secured.post("/chat", json={"message": "hi"}, headers={"X-API-Key": "other-key"})
        assert other.status_code == 401  # unknown key: auth, not rate limit


class TestTokenBucketUnit:
    def test_burst_then_deny_then_refill(self) -> None:
        bucket = TokenBucket(capacity=3, refill_per_second=100.0)
        allowed = [bucket.allow("c")[0] for _ in range(3)]
        assert allowed == [True, True, True]
        denied, retry_after = bucket.allow("c")
        assert denied is False and retry_after > 0
        import time

        time.sleep(0.05)
        ok, _ = bucket.allow("c")
        assert ok is True

    def test_clients_are_isolated(self) -> None:
        bucket = TokenBucket(capacity=1, refill_per_second=0.001)
        assert bucket.allow("a")[0] is True
        assert bucket.allow("b")[0] is True  # separate bucket
        assert bucket.allow("a")[0] is False
