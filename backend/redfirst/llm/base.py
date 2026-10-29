"""Provider-neutral LLM interface. Business logic depends only on this module."""

from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    prompt_name: str
    prompt_version: str


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    output: T
    model: str  # the model that actually served the request (may be a fallback)
    stop_reason: str | None
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def metadata(self, request: LLMRequest) -> dict[str, Any]:
        """What gets persisted on Attempt.llm_metadata."""
        return {
            "model": self.model,
            "prompt_name": request.prompt_name,
            "prompt_version": request.prompt_version,
            "stop_reason": self.stop_reason,
            "usage": self.usage,
            "request_id": self.request_id,
        }


class LLMError(Exception):
    """Base class. ``retryable`` tells the orchestrator whether a later retry may help."""

    retryable = False


class LLMUnavailable(LLMError):
    """Network failure, timeout, 5xx or rate limit after the SDK's own retries."""

    retryable = True


class LLMRejected(LLMError):
    """Bad request, auth or permission problem: a configuration bug, never retried."""


class LLMRefused(LLMError):
    """The model declined the request (stop_reason == "refusal")."""


class LLMInvalidOutput(LLMError):
    """The response was truncated or did not match the requested schema."""


class LLMProvider(Protocol):
    name: str

    def generate(self, request: LLMRequest, schema: type[T]) -> LLMResult[T]:
        """Return a validated ``schema`` instance or raise an ``LLMError``."""
        ...
