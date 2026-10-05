"""Pydantic schemas for the refund assistant (structured outputs, EVL-2).

``AgentDecision`` is the model's structured output contract; the JSON schema is
exported and hashed into run manifests (AST-1) and validated on every response.
Money is always paise integers - never floats.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, Field


class AgentAction(StrEnum):
    """The four things the refund assistant may do."""

    APPROVE = "approve"
    REFUSE = "refuse"
    ESCALATE = "escalate"
    ASK_INFO = "ask_info"


class AgentDecision(BaseModel):
    """Structured model output for one refund turn."""

    action: AgentAction
    amount_paise: int | None = Field(default=None, ge=0, le=10**12)
    order_id: str | None = Field(default=None, min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)


class AgentTurn(BaseModel):
    """Full result of one assistant turn, including the code-side policy guard."""

    decision: AgentDecision
    policy_blocked: bool = False
    sanitized_input_truncated: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0


@lru_cache(maxsize=1)
def decision_json_schema() -> dict[str, object]:
    """Exported JSON Schema for AgentDecision (versioned artifact, AST-1)."""
    return AgentDecision.model_json_schema()
