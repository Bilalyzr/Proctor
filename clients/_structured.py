"""Structured-output parsing shared by all adapters.

Real models frequently wrap JSON in prose or code fences even when asked not
to, so parsing is strict-first with one bounded recovery attempt (extract the
outermost JSON object) before raising ``StructuredOutputError``.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from clients.base import StructuredOutputError


def parse_structured(text: str, model_cls: type[BaseModel]) -> BaseModel:
    """Validate model output against a Pydantic schema.

    Tries the whole text first, then the outermost ``{...}`` span. Raises
    ``StructuredOutputError`` carrying the validation errors either way.
    """
    for candidate in _candidates(text):
        try:
            return model_cls.model_validate_json(candidate)
        except ValidationError:
            continue
    try:
        return model_cls.model_validate_json(text)
    except ValidationError as exc:
        msg = f"model output failed schema validation for {model_cls.__name__}: {exc}"
        raise StructuredOutputError(msg) from exc


def _candidates(text: str) -> list[str]:
    """Bounded recovery candidates (outermost brace span), if any."""
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        first = stripped.find("{")
        last = stripped.rfind("}")
        if first != -1 and last > first:
            return [stripped[first : last + 1]]
    return []
