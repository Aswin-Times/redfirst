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

    def metadata(self, request: LLMRequest,
                 provider: "LLMProvider | None" = None) -> dict[str, Any]:
        """What gets persisted on Attempt.llm_metadata for a successful call."""
        return attempt_metadata(
            provider if provider is not None else _Anonymous(self.model), request,
            call_status="succeeded", usage=self.usage or None, served_model=self.model,
            request_id=self.request_id, stop_reason=self.stop_reason,
        )


@dataclass(frozen=True)
class _Anonymous:
    model: str
    name: str | None = None


class LLMError(Exception):
    """Base class. ``retryable`` tells the orchestrator whether a later retry may help.

    Carries whatever the provider actually returned before failing (request id, HTTP status,
    served model, token usage). Anything not returned stays None; nothing is estimated.
    """

    retryable = False
    call_status = "provider_error"  # how the failed call is recorded on the attempt

    def __init__(self, message: str = "", *, request_id: str | None = None,
                 status_code: int | None = None, usage: dict[str, int] | None = None,
                 served_model: str | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.status_code = status_code
        self.usage = usage
        self.served_model = served_model


class LLMUnavailable(LLMError):
    """Network failure, timeout, 5xx or rate limit after the SDK's own retries."""

    retryable = True


class LLMRejected(LLMError):
    """Bad request, auth or permission problem: a configuration bug, never retried."""


class LLMRefused(LLMError):
    """The model declined the request (stop_reason == "refusal")."""

    call_status = "refused"


class LLMInvalidOutput(LLMError):
    """The response was truncated or did not match the requested schema."""

    call_status = "invalid_output"


class LLMProvider(Protocol):
    name: str
    model: str  # the configured model; the served model may differ (fallbacks)

    def generate(self, request: LLMRequest, schema: type[T]) -> LLMResult[T]:
        """Return a validated ``schema`` instance or raise an ``LLMError``."""
        ...


def attempt_metadata(
    provider: LLMProvider,
    request: LLMRequest,
    *,
    call_status: str,
    usage: dict[str, int] | None = None,
    served_model: str | None = None,
    request_id: str | None = None,
    status_code: int | None = None,
    stop_reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """What gets persisted on Attempt.llm_metadata, for successful and failed calls alike.

    ``usage`` is None when the provider did not report it (``usage_known`` False); token
    budgets only count known usage.
    """
    configured = getattr(provider, "model", None)
    return {
        "provider": getattr(provider, "name", None),
        "configured_model": configured,
        "model": served_model or configured,
        "prompt_name": request.prompt_name,
        "prompt_version": request.prompt_version,
        "call_status": call_status,
        "stop_reason": stop_reason,
        "usage": usage,
        "usage_known": usage is not None,
        "request_id": request_id,
        "status_code": status_code,
        "error": error,
    }
