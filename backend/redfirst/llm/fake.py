"""Deterministic scripted provider for tests. Never used in production code paths."""

from pydantic import BaseModel

from redfirst.llm.base import LLMError, LLMRequest, LLMResult, T


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, script: list[BaseModel | LLMError]) -> None:
        self._script = list(script)
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest, schema: type[T]) -> LLMResult[T]:
        self.requests.append(request)
        if not self._script:
            raise AssertionError("FakeProvider script exhausted")
        item = self._script.pop(0)
        if isinstance(item, LLMError):
            raise item
        return LLMResult(output=schema.model_validate(item.model_dump()), model="fake-model",
                         stop_reason="end_turn", usage={"input_tokens": 0, "output_tokens": 0})
