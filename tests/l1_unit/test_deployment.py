"""Deployment validation artifacts (checklist: CI/CD deployment validation).

Docker build + compose up run in CI (ubuntu runners have docker); locally
these tests statically validate the artifacts so drift fails fast, and the
/health endpoint (the runtime deployment probe) is exercised in-process.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from sut.api import create_app

pytestmark = [pytest.mark.l1, pytest.mark.smoke]

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDeploymentArtifacts:
    def test_dockerfile_builds_the_sut_with_healthcheck(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "FROM python:3.11-slim" in dockerfile
        assert "pip install --no-cache-dir ." in dockerfile
        assert "USER appuser" in dockerfile  # non-root
        assert "HEALTHCHECK" in dockerfile and "/health" in dockerfile
        assert "uvicorn" in dockerfile and "sut.api:app" in dockerfile

    def test_compose_service_gates_on_health(self) -> None:
        compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        service = compose["services"]["proctor-sut"]
        assert service["build"] == "."
        assert "/health" in service["healthcheck"]["test"][-1]
        # host port binding is localhost-only
        assert service["ports"] == ["127.0.0.1:8000:8000"]

    def test_runtime_packages_are_selfcontained(self) -> None:
        """The Dockerfile copies exactly the runtime packages pyproject ships."""
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        for package in ("framework/", "clients/", "sut/"):
            assert package in dockerfile
        # dev-only folders are not shipped in the image
        for folder in ("tests/", "guardrails/", "synthetic/"):
            assert folder not in dockerfile


def test_health_endpoint_is_the_deployment_probe() -> None:
    client = TestClient(create_app(api_key=None, rate_limit=None))
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {"provider", "tier", "auth", "rate_limited"} <= set(body)
