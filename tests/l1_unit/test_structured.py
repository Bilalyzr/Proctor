"""Rank-1 unit tests: structured-output parsing shared by all adapters."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from clients._structured import parse_structured
from clients.base import StructuredOutputError

pytestmark = pytest.mark.l1


class Pet(BaseModel):
    name: str
    age: int


def test_parses_clean_json() -> None:
    pet = parse_structured(json.dumps({"name": "Rex", "age": 3}), Pet)
    assert pet.name == "Rex"


def test_recovers_fenced_or_prose_wrapped_json() -> None:
    wrapped = 'Sure! Here is the JSON:\n```json\n{"name": "Rex", "age": 3}\n```'
    pet = parse_structured(wrapped, Pet)
    assert pet.age == 3


def test_invalid_schema_raises_structured_output_error() -> None:
    with pytest.raises(StructuredOutputError, match="Pet"):
        parse_structured('{"name": 123}', Pet)  # age missing, name wrong type


def test_garbage_raises_structured_output_error() -> None:
    with pytest.raises(StructuredOutputError):
        parse_structured("no braces at all", Pet)


def test_recovered_candidate_failing_falls_back_to_whole_text() -> None:
    # the inner brace span exists but is invalid -> fallback -> still invalid -> error
    with pytest.raises(StructuredOutputError):
        parse_structured('prefix {"name": 42} suffix', Pet)
