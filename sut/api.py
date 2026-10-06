"""FastAPI app exposing the guarded refund assistant (rank-9 E2E substrate).

``POST /chat`` runs the full inline-guardrail pipeline (PRD-1) around the
assistant turn. ``create_app`` adds the API-security layer from the E2E
checklist: optional API-key authentication (``X-API-Key``) and a per-client
token-bucket rate limiter (HTTP 401 / 429). The module-level ``app`` stays
keyless and unlimited so offline journeys and CI run unchanged.
"""

from __future__ import annotations

import hmac
import os
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
from sut.sanitize import sanitize_input

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

    max_clients = 10_000  # bounded memory under identity floods (audit A1)

    def allow(self, client: str) -> tuple[bool, float]:
        now = time.monotonic()
        if len(self._tokens) >= self.max_clients and client not in self._tokens:
            # evict the stalest identities instead of growing forever
            for stale in sorted(self._last, key=self._last.__getitem__)[: self.max_clients // 10]:
                self._tokens.pop(stale, None)
                self._last.pop(stale, None)
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
    # sanitize BEFORE classifying: the guardrail must inspect the same bytes
    # the model will see (audit C1 - zero-width/markup reassembly bypass)
    sanitized = sanitize_input(
        request.message,
        max_chars=SETTINGS.sanitize_max_chars,
        strip_markup=SETTINGS.sanitize_strip_markup,
    )
    inbound = PIPELINE.check_inbound(sanitized.text)
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
    turn = assistant.handle(sanitized.text, order_id=request.order_id)
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
    """Build the app with the requested API-security posture.

    Security properties (audit run-1 fixes):
    - the rate limiter keys buckets on the SERVER-derived client host,
      never on a client-supplied header value, and runs BEFORE auth so
      failed-auth guessing is throttled too (A1/A2/A5);
    - auth uses a constant-time comparison (A3);
    - /health is exempt from both controls for healthchecks.
    """
    app = FastAPI(title="ShopFast Refund Assistant", version="1.2.0")
    bucket = TokenBucket(*rate_limit) if rate_limit else None

    @app.middleware("http")
    async def security_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        # /health stays open: container healthchecks and load balancers
        # probe it without credentials
        if request.url.path == "/health":
            return await call_next(request)
        # throttle first, on a server-derived identity (client host), so
        # both authenticated traffic AND failed-auth guessing are bounded
        if bucket is not None:
            identity = request.client.host if request.client else "anonymous"
            allowed, retry_after = bucket.allow(identity)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": f"{retry_after:.2f}"},
                    content={"detail": "rate limit exceeded"},
                )
        if api_key is not None:
            provided = request.headers.get("X-API-Key", "")
            if not hmac.compare_digest(provided.encode(), api_key.encode()):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid or missing API key"},
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


# deployment: authenticated + rate-limited when AIQA_API_KEY is set;
# keyless offline posture otherwise (CI journeys unchanged)
_DEPLOY_KEY = os.environ.get("AIQA_API_KEY") or None
app = create_app(
    api_key=_DEPLOY_KEY,
    rate_limit=(30, 10.0) if _DEPLOY_KEY else None,
)
