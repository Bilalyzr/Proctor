"""FastAPI app exposing the guarded refund assistant (rank-9 E2E substrate).

``POST /chat`` runs the full inline-guardrail pipeline (PRD-1) around the
assistant turn. ``create_app`` adds the API-security layer from the E2E
checklist: optional API-key authentication (``X-API-Key``) and a per-client
token-bucket rate limiter (HTTP 401 / 429). The module-level ``app`` stays
keyless and unlimited so offline journeys and CI run unchanged.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from clients.mock import MockClient
from framework.config import Settings
from guardrails import GuardrailPipeline
from sut.agent import RefundAssistant

SETTINGS = Settings(_env_file=None)
PIPELINE = GuardrailPipeline()

_WEB_DIR = Path(__file__).resolve().parent / "web"


class TokenBucket:
    """Minimal token-bucket rate limiter (capacity, refill per second)."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = capacity
        self.refill = refill_per_second
        self._tokens: dict[str, float] = {}
        self._last: dict[str, float] = {}

    def allow(self, client: str) -> tuple[bool, float]:
        now = time.monotonic()
        if client not in self._tokens:
            # first sight of this client: full bucket, clock starts now
            self._tokens[client] = float(self.capacity)
            self._last[client] = now
        elapsed = max(0.0, now - self._last[client])
        self._last[client] = now
        self._tokens[client] = min(
            float(self.capacity), self._tokens[client] + elapsed * self.refill
        )
        if self._tokens[client] >= 1.0:
            self._tokens[client] -= 1.0
            return True, self._tokens[client]
        retry_after = (1.0 - self._tokens[client]) / self.refill
        return False, retry_after


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


def _chat_logic(request: ChatRequest) -> ChatResponse:
    inbound = PIPELINE.check_inbound(request.message)
    if not inbound.allowed:
        return ChatResponse(
            reply=(
                "Your message was blocked by our safety filters. Please rephrase and try again."
            ),
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


def create_app(
    *,
    api_key: str | None = None,
    rate_limit: tuple[int, float] | None = (30, 10.0),
) -> FastAPI:
    """Build the app with the requested API-security posture."""
    app = FastAPI(title="ShopFast Refund Assistant", version="1.1.0")
    bucket = TokenBucket(*rate_limit) if rate_limit else None

    @app.middleware("http")
    async def security_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        # /health stays open: container healthchecks and load balancers
        # probe it without credentials
        if api_key is not None and request.url.path != "/health":
            provided = request.headers.get("X-API-Key", "")
            if provided != api_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid or missing API key"},
                )
        if bucket is not None and request.url.path == "/chat" and request.method == "POST":
            client = request.headers.get("X-API-Key") or (
                request.client.host if request.client else "anonymous"
            )
            allowed, retry_after = bucket.allow(client)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": f"{retry_after:.2f}"},
                    content={"detail": "rate limit exceeded"},
                )
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((_WEB_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": SETTINGS.provider,
            "tier": SETTINGS.tier,
            "auth": api_key is not None,
            "rate_limited": bucket is not None,
        }

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        return _chat_logic(request)

    @app.get("/metrics")
    def metrics() -> dict[str, Any]:
        return PIPELINE.stats()

    return app


# default deployment: keyless, unlimited - offline journeys and CI unchanged
app = create_app(api_key=None, rate_limit=None)
