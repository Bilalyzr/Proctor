"""FastAPI app exposing the guarded refund assistant (rank-9 E2E substrate).

``POST /chat`` runs the full inline-guardrail pipeline (PRD-1) around the
assistant turn: inbound injection/brand checks before the model, outbound
DLP/infra/brand checks before the reply. ``GET /health`` for journeys.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from clients.mock import MockClient
from framework.config import Settings
from guardrails import GuardrailPipeline
from sut.agent import RefundAssistant

app = FastAPI(title="ShopFast Refund Assistant", version="1.0.0")

_WEB_DIR = Path(__file__).resolve().parent / "web"

SETTINGS = Settings(_env_file=None)
PIPELINE = GuardrailPipeline()


class ChatRequest(BaseModel):
    message: str = Field(min_length=0, max_length=8000)
    order_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    reply: str
    action: str
    blocked: bool = False
    blocking_rules: list[str] = Field(default_factory=list)


def _assistant() -> RefundAssistant:
    client = MockClient(SETTINGS.model_name_for("mock"), seed=SETTINGS.seed)
    return RefundAssistant(client, settings=SETTINGS)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((_WEB_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "provider": SETTINGS.provider, "tier": SETTINGS.tier}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    inbound = PIPELINE.check_inbound(request.message)
    if not inbound.allowed:
        return ChatResponse(
            reply="Your message was blocked by our safety filters. Please rephrase and try again.",
            action="blocked",
            blocked=True,
            blocking_rules=inbound.blocking_rules,
        )
    assistant = _assistant()
    turn = assistant.handle(request.message, order_id=request.order_id)
    outbound = PIPELINE.check_outbound(turn.decision.message)
    if not outbound.allowed:
        return ChatResponse(
            reply="I can't share that response; a human agent will follow up.",
            action="blocked",
            blocked=True,
            blocking_rules=outbound.blocking_rules,
        )
    return ChatResponse(
        reply=outbound.text,
        action=turn.decision.action.value,
        blocked=False,
        blocking_rules=[],
    )


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    return PIPELINE.stats()
