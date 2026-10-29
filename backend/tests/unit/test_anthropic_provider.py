"""AnthropicProvider with a stubbed SDK client: no network, no API key."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from redfirst.core.config import Settings
from redfirst.llm.anthropic_provider import AnthropicProvider
from redfirst.llm.base import (
    LLMInvalidOutput,
    LLMRefused,
    LLMRejected,
    LLMRequest,
    LLMUnavailable,
)

REQ = LLMRequest(system="sys", user="usr", prompt_name="p", prompt_version="v1")


class Out(BaseModel):
    x: int


class StubClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self._result, self._error = result, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result


_DEFAULT = object()


def response(stop_reason="end_turn", parsed=_DEFAULT):
    parsed = Out(x=1) if parsed is _DEFAULT else parsed
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, model="claude-opus-5-5",
                           stop_details=None,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def api_error(cls, status):
    resp = httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com"))
    return cls("boom", response=resp, body=None)


def provider(stub, **settings):
    return AnthropicProvider(Settings(**settings), client=stub)


def test_success_sends_structured_output_effort_and_fallbacks():
    stub = StubClient(result=response())
    result = provider(stub).generate(REQ, Out)
    assert result.output == Out(x=1) and result.model == "claude-opus-5-5"
    call = stub.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_format"] is Out
    assert call["output_config"] == {"effort": "high"}
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["system"] == "sys" and call["messages"][0]["content"] == "usr"
    assert "temperature" not in call and "tool_choice" not in call
    assert result.metadata(REQ)["usage"] == {"input_tokens": 10, "output_tokens": 5}


def test_fallbacks_can_be_disabled():
    stub = StubClient(result=response())
    provider(stub, llm_refusal_fallbacks=False).generate(REQ, Out)
    assert "fallbacks" not in stub.calls[0] and "betas" not in stub.calls[0]


@pytest.mark.parametrize("stop", ["refusal"])
def test_refusal(stop):
    with pytest.raises(LLMRefused):
        provider(StubClient(result=response(stop_reason=stop))).generate(REQ, Out)


def test_truncation_and_missing_output_are_invalid():
    with pytest.raises(LLMInvalidOutput):
        provider(StubClient(result=response(stop_reason="max_tokens"))).generate(REQ, Out)
    with pytest.raises(LLMInvalidOutput):
        provider(StubClient(result=response(parsed=None))).generate(REQ, Out)


@pytest.mark.parametrize(("cls", "status", "expected"), [
    (anthropic.RateLimitError, 429, LLMUnavailable),
    (anthropic.InternalServerError, 500, LLMUnavailable),
    (anthropic.BadRequestError, 400, LLMRejected),
    (anthropic.AuthenticationError, 401, LLMRejected),
    (anthropic.NotFoundError, 404, LLMRejected),
])
def test_status_errors_are_mapped(cls, status, expected):
    with pytest.raises(expected) as info:
        provider(StubClient(error=api_error(cls, status))).generate(REQ, Out)
    assert info.value.retryable is (expected is LLMUnavailable)


def test_connection_error_is_unavailable():
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    with pytest.raises(LLMUnavailable):
        provider(StubClient(error=err)).generate(REQ, Out)
