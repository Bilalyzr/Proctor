"""Shared fixtures for the multi-domain suites."""

from __future__ import annotations

import pytest

from domains.base import DomainPack
from domains.registry import get_pack, list_packs


@pytest.fixture(params=[pack.id for pack in list_packs()], ids=lambda pack_id: pack_id)
def pack(request) -> DomainPack:
    return get_pack(request.param)
