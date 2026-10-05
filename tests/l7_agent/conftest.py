"""Shared fixtures for the agentic suites."""

from __future__ import annotations

import pytest

from breakers import BreakerMonitor
from sut.agent_loop import RefundAgent
from sut.tools.base import RefundLedger, build_default_registry, load_orders


@pytest.fixture()
def registry():
    return build_default_registry(orders=load_orders(), ledger=RefundLedger())


@pytest.fixture()
def agent(registry) -> RefundAgent:
    return RefundAgent(registry=registry)


@pytest.fixture()
def monitor() -> BreakerMonitor:
    return BreakerMonitor()
