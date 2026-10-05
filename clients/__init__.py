"""Provider-agnostic model client (blueprint Section 13, "Model client").

LiteLLM-style surface: one ``complete(request) -> response`` call regardless of
provider. The deterministic MOCK provider is the default so the whole framework
runs offline in CI with no API keys; real adapters import their SDK lazily and
activate only when their API key is present in the environment.
"""

from clients.base import (
    BaseClient,
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    ModelClient,
    ModelClientError,
    ProviderNotConfigured,
    StructuredOutputError,
    TokenUsage,
    TransientModelError,
)

__all__ = [
    "BaseClient",
    "ChatMessage",
    "CompletionRequest",
    "CompletionResponse",
    "ModelClient",
    "ModelClientError",
    "ProviderNotConfigured",
    "StructuredOutputError",
    "TokenUsage",
    "TransientModelError",
]
