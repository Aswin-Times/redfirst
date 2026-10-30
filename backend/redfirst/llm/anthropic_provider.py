"""Claude via the official Anthropic SDK, using structured outputs (``messages.parse``).

The SDK already retries connection errors, 408/409/429 and 5xx with backoff
(``max_retries``); this adapter only maps the final outcome onto ``LLMError`` types.
"""

import anthropic
from pydantic import ValidationError

from redfirst.core.config import Settings
from redfirst.llm.base import (
    LLMInvalidOutput,
    LLMRefused,
    LLMRejected,
    LLMRequest,
    LLMResult,
    LLMUnavailable,
    T,
)

_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        self._settings = settings
        self.model = settings.llm_model
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
        self._client = client or anthropic.Anthropic(
            api_key=key,  # None -> SDK resolves ANTHROPIC_API_KEY / profiles itself
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    def generate(self, request: LLMRequest, schema: type[T]) -> LLMResult[T]:
        s = self._settings
        extra = {}
        if s.llm_refusal_fallbacks:  # on a refusal, the API reruns on a fallback model
            extra = {"betas": [_FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = self._client.beta.messages.parse(
                model=s.llm_model,
                max_tokens=s.llm_max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                output_format=schema,
                output_config={"effort": s.llm_effort},
                **extra,
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable(f"rate limited after retries: {exc.message}",
                                 **_status_context(exc)) from exc
        except (anthropic.BadRequestError, anthropic.AuthenticationError,
                anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
            raise LLMRejected(f"{type(exc).__name__}: {exc.message}",
                              **_status_context(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMUnavailable(f"server error {exc.status_code}",
                                     **_status_context(exc)) from exc
            raise LLMRejected(f"API error {exc.status_code}: {exc.message}",
                              **_status_context(exc)) from exc
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise LLMUnavailable(f"connection failed: {exc}") from exc
        except ValidationError as exc:  # the SDK failed to parse: no response object, no usage
            raise LLMInvalidOutput(f"output did not match schema: {str(exc)[:1000]}") from exc

        context = _response_context(response)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMRefused(f"model refused (category={category})", **context)
        if response.stop_reason == "max_tokens":
            raise LLMInvalidOutput("response truncated at max_tokens", **context)
        if response.parsed_output is None:
            raise LLMInvalidOutput("no structured output in response", **context)

        return LLMResult(
            output=response.parsed_output,
            model=response.model,
            stop_reason=response.stop_reason,
            usage=context["usage"] or {},
            request_id=context["request_id"],
        )


def _status_context(exc: anthropic.APIStatusError) -> dict:
    request_id = getattr(exc, "request_id", None)
    if request_id is None:
        response = getattr(exc, "response", None)
        request_id = response.headers.get("request-id") if response is not None else None
    return {"status_code": exc.status_code, "request_id": request_id}


def _response_context(response) -> dict:
    usage = getattr(response, "usage", None)
    known = ({"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
             if usage is not None else None)
    return {"usage": known, "request_id": getattr(response, "_request_id", None),
            "served_model": getattr(response, "model", None)}
