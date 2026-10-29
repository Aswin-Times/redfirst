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
            raise LLMUnavailable(f"rate limited after retries: {exc.message}") from exc
        except (anthropic.BadRequestError, anthropic.AuthenticationError,
                anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
            raise LLMRejected(f"{type(exc).__name__}: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMUnavailable(f"server error {exc.status_code}") from exc
            raise LLMRejected(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise LLMUnavailable(f"connection failed: {exc}") from exc
        except ValidationError as exc:
            raise LLMInvalidOutput(f"output did not match schema: {exc}") from exc

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMRefused(f"model refused (category={category})")
        if response.stop_reason == "max_tokens":
            raise LLMInvalidOutput("response truncated at max_tokens")
        if response.parsed_output is None:
            raise LLMInvalidOutput("no structured output in response")

        usage = response.usage
        return LLMResult(
            output=response.parsed_output,
            model=response.model,
            stop_reason=response.stop_reason,
            usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
            request_id=getattr(response, "_request_id", None),
        )
