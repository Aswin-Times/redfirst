"""D7: every LLM attempt records what is actually known about the call, including failures.

Token usage is recorded only when the provider reported it (``usage_known``); it is never
invented. Calls refused by REDFIRST's own budget before reaching the provider are recorded as
``not_sent`` and do not count as provider calls.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from redfirst.db.models import Attempt
from redfirst.db.session import session_scope
from redfirst.generation.generator import generate_once
from redfirst.llm.base import LLMInvalidOutput, LLMRefused, LLMResult, LLMUnavailable
from redfirst.llm.fake import FakeProvider
from redfirst.llm.prompts import load_prompt
from redfirst.worker.orchestrator import Deps
from tests.integration.test_pipeline_e2e import (  # noqa: F401  (make_env is a fixture)
    BOUNDARY,
    make_env,
    run,
)

PROMPT = load_prompt("generate_test", "v2")
MODULES = {"shop": "shop/__init__.py", "shop.discounts": "shop/discounts.py"}


def once(item):
    return generate_once(FakeProvider([item]), PROMPT, number=1, report_text="R",
                         evidence_text="E", modules=MODULES)


def test_successful_call_records_known_usage():
    meta = once(BOUNDARY).llm_metadata
    assert meta["call_status"] == "succeeded" and meta["usage_known"] is True
    assert meta["prompt_name"] == "generate_test" and meta["prompt_version"] == "v2"
    assert meta["configured_model"] == "fake-model" and meta["model"] == "fake-model"


def test_invalid_output_with_reported_usage_keeps_it():
    rec = once(LLMInvalidOutput("truncated at max_tokens", request_id="req_1",
                                usage={"input_tokens": 50, "output_tokens": 16000},
                                served_model="claude-opus-5-5"))
    meta = rec.llm_metadata
    assert meta is not None, "failed attempts must still be recorded"
    assert meta["call_status"] == "invalid_output"
    assert meta["usage"] == {"input_tokens": 50, "output_tokens": 16000} and meta["usage_known"]
    assert meta["request_id"] == "req_1" and meta["model"] == "claude-opus-5-5"
    assert meta["prompt_version"] == "v2" and "truncated" in meta["error"]


def test_invalid_output_without_usage_records_it_as_unknown():
    meta = once(LLMInvalidOutput("did not match schema")).llm_metadata
    assert meta["call_status"] == "invalid_output"
    assert meta["usage"] is None and meta["usage_known"] is False
    assert meta["model"] == "fake-model"  # configured model, since none was reported


def test_provider_error_records_partial_metadata():
    rec = once(LLMUnavailable("server error 503", status_code=503, request_id="req_2"))
    meta = rec.llm_metadata
    assert meta["call_status"] == "provider_error" and meta["status_code"] == 503
    assert meta["request_id"] == "req_2" and meta["usage_known"] is False
    assert rec.llm_error is not None


def test_refusal_is_its_own_status():
    meta = once(LLMRefused("declined", usage={"input_tokens": 10, "output_tokens": 0})).llm_metadata
    assert meta["call_status"] == "refused" and meta["usage_known"]


class MeteredProvider(FakeProvider):
    """Fake provider that reports usage on success, like the real adapter."""

    def generate(self, request, schema):
        result = super().generate(request, schema)
        return LLMResult(result.output, result.model, result.stop_reason,
                         {"input_tokens": 400, "output_tokens": 0})


def with_provider(env, provider):
    env.deps = Deps(**{**env.deps.__dict__, "provider": provider})
    env.provider = provider


def attempts(env):
    with session_scope(env.deps.engine) as s:
        return [(a.number, a.status, a.llm_metadata) for a in
                s.scalars(select(Attempt).order_by(Attempt.created_at, Attempt.number))]


def test_token_budget_counts_known_usage_from_failed_attempts(make_env, tmp_path):  # noqa: F811
    env = make_env([], llm_token_budget_per_investigation=900)
    with_provider(env, MeteredProvider([
        LLMInvalidOutput("truncated", usage={"input_tokens": 600, "output_tokens": 300}),
        BOUNDARY]))
    report = run(env, "boundary_bug", tmp_path)
    assert report.state == "FAILED" and report.error["type"] == "LLMBudgetExceeded"
    rows = attempts(env)
    assert [r[1] for r in rows] == ["invalid_output", "blocked"]
    assert rows[1][2]["call_status"] == "not_sent"
    assert rows[1][2]["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert len(env.provider.requests) == 1


def test_unknown_usage_is_not_invented_into_the_budget(make_env, tmp_path):  # noqa: F811
    env = make_env([], llm_token_budget_per_investigation=500)
    with_provider(env, MeteredProvider([LLMInvalidOutput("schema mismatch"), BOUNDARY]))
    report = run(env, "boundary_bug", tmp_path)
    assert report.outcome == "REPRODUCED"  # the unknown-usage attempt did not consume budget
    rows = attempts(env)
    assert rows[0][2]["usage_known"] is False and rows[1][2]["usage"]["input_tokens"] == 400


def test_blocked_attempts_do_not_count_towards_the_daily_call_cap(make_env, tmp_path):  # noqa: F811
    env = make_env([BOUNDARY], llm_max_calls_per_day=1)
    assert run(env, "boundary_bug", tmp_path).outcome == "REPRODUCED"     # 1 real call
    with_provider(env, FakeProvider([BOUNDARY]))
    assert run(env, "boundary_bug", tmp_path).error["type"] == "LLMBudgetExceeded"  # blocked
    with session_scope(env.deps.engine) as s:  # the real call ages out of the 24h window
        for a in s.scalars(select(Attempt).where(Attempt.status != "blocked")):
            a.created_at = datetime.now(UTC) - timedelta(hours=25)
    with_provider(env, FakeProvider([BOUNDARY]))
    assert run(env, "boundary_bug", tmp_path).outcome == "REPRODUCED"     # blocked one ignored
