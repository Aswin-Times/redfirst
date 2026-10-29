"""Abuse controls end to end: LLM budgets, queue cap, input caps, redaction, retention."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from redfirst.api.app import create_app
from redfirst.core.config import Settings
from redfirst.db.models import (
    Attempt,
    Base,
    BugReport,
    EvidenceRecord,
    ExecutionResult,
    Investigation,
    InvestigationEvent,
    Repository,
)
from redfirst.db.retention import purge_older_than
from redfirst.db.session import make_engine, session_scope
from redfirst.llm.base import LLMResult
from redfirst.llm.fake import FakeProvider
from tests.conftest import zip_fixture
from tests.integration.test_pipeline_e2e import (  # noqa: F401  (make_env is a fixture)
    BOUNDARY,
    gen,
    make_env,
    run,
    seed,
)

BAD = gen("import subprocess\n" + BOUNDARY.test_code, BOUNDARY.target_modules, "AssertionError")


class MeteredProvider(FakeProvider):
    """Fake provider that reports token usage, like the real adapter does."""

    def __init__(self, script, tokens=1000):
        super().__init__(script)
        self.tokens = tokens

    def generate(self, request, schema):
        result = super().generate(request, schema)
        return LLMResult(result.output, result.model, result.stop_reason,
                         {"input_tokens": self.tokens, "output_tokens": 0})


def with_provider(env, provider):
    from redfirst.worker.orchestrator import Deps

    env.deps = Deps(**{**env.deps.__dict__, "provider": provider})
    env.provider = provider


# -- LLM quota abuse -----------------------------------------------------------------------
def test_token_budget_stops_further_llm_calls(make_env, tmp_path):  # noqa: F811
    env = make_env([], llm_token_budget_per_investigation=1500)
    provider = MeteredProvider([BAD, BAD2()], tokens=1000)
    with_provider(env, provider)
    report = run(env, "boundary_bug", tmp_path)
    assert report.state == "FAILED" and report.outcome == "EXECUTION_ERROR"
    assert report.error["type"] == "LLMBudgetExceeded" and report.error["retryable"] is True
    assert "token budget" in report.error["detail"]
    assert len(provider.requests) == 2  # third call was refused before it was made


def BAD2():
    return gen("import os\n" + BOUNDARY.test_code, BOUNDARY.target_modules, "AssertionError")


def test_daily_call_cap_applies_across_investigations(make_env, tmp_path):  # noqa: F811
    env = make_env([BOUNDARY], llm_max_calls_per_day=1)
    first = run(env, "boundary_bug", tmp_path)
    assert first.outcome == "REPRODUCED"
    provider = FakeProvider([BOUNDARY])
    with_provider(env, provider)
    second = run(env, "boundary_bug", tmp_path)
    assert second.state == "FAILED" and second.error["type"] == "LLMBudgetExceeded"
    assert "daily limit" in second.error["detail"]
    assert provider.requests == []


def test_old_calls_do_not_count_towards_daily_cap(make_env, tmp_path):  # noqa: F811
    env = make_env([BOUNDARY, BOUNDARY], llm_max_calls_per_day=1)
    run(env, "boundary_bug", tmp_path)
    with session_scope(env.deps.engine) as s:  # age the first attempt past the 24h window
        for attempt in s.scalars(select(Attempt)):
            attempt.created_at = datetime.now(UTC) - timedelta(hours=25)
    assert run(env, "boundary_bug", tmp_path).outcome == "REPRODUCED"


# -- redaction -----------------------------------------------------------------------------
SECRET = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


def test_secrets_printed_by_tests_never_reach_storage_report_or_next_prompt(make_env, tmp_path):  # noqa: F811
    # The key is assembled at run time, as if read from somewhere: the test's own source must
    # not contain it, because source code is legitimately shown in the report.
    head, tail = SECRET[:7], SECRET[7:]
    leaky = gen(
        "from shop.discounts import discount_rate\n\n"
        "def test_control():\n    assert discount_rate(150) == 0.1\n\n"
        "def test_reproduces_bug():\n"
        f"    key = '{head}' + '{tail}'\n"
        "    print('ANTHROPIC_API_KEY=' + key)\n"
        "    print('token', key)\n"
        "    assert discount_rate(100) == 0.1\n",
        ["shop/discounts.py"], "AssertionError")
    assert SECRET not in leaky.test_code
    env = make_env([leaky])
    report = run(env, "boundary_bug", tmp_path)
    assert report.outcome == "REPRODUCED"
    assert SECRET not in report.model_dump_json()
    assert "[REDACTED]" in report.attempts[0].executions[0].output_excerpt
    with session_scope(env.deps.engine) as s:
        for row in s.scalars(select(ExecutionResult)):
            for ref in (row.stdout_ref, row.stderr_ref):
                if ref:
                    assert SECRET not in env.deps.blobs.read_text(ref)
            assert SECRET not in json.dumps(row.parsed)
        assert SECRET not in json.dumps([r.payload for r in s.scalars(select(EvidenceRecord))])


# -- queue and input caps ------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", max_pending_investigations=2)
    engine = make_engine(f"sqlite:///{tmp_path / 'cap.db'}")
    Base.metadata.create_all(engine)
    app = create_app(settings, engine)
    return TestClient(app), tmp_path


def _project_with_repo(client, tmp):
    pid = client.post("/api/projects", json={"name": "p"}).json()["id"]
    with open(zip_fixture("no_bug", tmp), "rb") as fh:
        repo = client.post(f"/api/projects/{pid}/repositories",
                           files={"archive": ("r.zip", fh, "application/zip")}).json()
    return pid, repo["id"]


def test_pending_queue_is_capped_and_finished_ones_do_not_count(client):
    c, tmp = client
    pid, rid = _project_with_repo(c, tmp)
    body = {"repository_id": rid, "bug_report": {"title": "x"}}
    ids = [c.post(f"/api/projects/{pid}/investigations", json=body).json()["id"] for _ in range(2)]
    r = c.post(f"/api/projects/{pid}/investigations", json=body)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert c.post(f"/api/investigations/{ids[0]}/cancel").status_code == 200
    assert c.post(f"/api/projects/{pid}/investigations", json=body).status_code == 201


@pytest.mark.parametrize(("field", "size"), [
    ("title", 301), ("description", 20_001), ("expected_behavior", 10_001),
    ("actual_behavior", 10_001), ("reproduction_steps", 10_001), ("stack_trace", 50_001),
    ("environment", 5_001),
])
def test_oversized_report_fields_are_rejected(client, field, size):
    c, tmp = client
    pid, rid = _project_with_repo(c, tmp)
    r = c.post(f"/api/projects/{pid}/investigations", json={
        "repository_id": rid, "bug_report": {"title": "x", field: "a" * size}})
    assert r.status_code == 422


# -- retention -----------------------------------------------------------------------------
def _finished(make_env, tmp_path):  # noqa: F811
    env = make_env([BOUNDARY])
    report = run(env, "boundary_bug", tmp_path)
    return env, report.investigation_id


def test_delete_removes_rows_and_unshared_logs_but_keeps_repository(make_env, tmp_path):  # noqa: F811
    env, inv_id = _finished(make_env, tmp_path)
    with session_scope(env.deps.engine) as s:
        refs = {r for row in s.execute(select(ExecutionResult.stdout_ref,
                                              ExecutionResult.stderr_ref)) for r in row if r}
    assert refs and all(env.deps.blobs.path(k) for k in refs)

    app = create_app(env.deps.settings, env.deps.engine)
    c = TestClient(app)
    assert c.delete(f"/api/investigations/{inv_id}").status_code == 204
    assert c.get(f"/api/investigations/{inv_id}").status_code == 404
    with session_scope(env.deps.engine) as s:
        assert s.scalars(select(Investigation)).all() == []
        assert s.scalars(select(InvestigationEvent)).all() == []
        assert s.scalars(select(ExecutionResult)).all() == []
        assert s.scalars(select(EvidenceRecord)).all() == []
        assert s.scalars(select(BugReport)).all() == []
        repo = s.scalars(select(Repository)).one()
        env.deps.blobs.path(repo.storage_ref)  # archive blob survives: the repo still exists
    for key in refs:
        with pytest.raises(FileNotFoundError):
            env.deps.blobs.path(key)


def test_running_investigation_cannot_be_deleted(make_env, tmp_path):  # noqa: F811
    env = make_env([])
    inv_id = seed(env, "no_bug", tmp_path)
    c = TestClient(create_app(env.deps.settings, env.deps.engine))
    r = c.delete(f"/api/investigations/{inv_id}")
    assert r.status_code == 409 and "cancel" in r.json()["detail"]
    assert c.delete("/api/investigations/missing").status_code == 404


def test_shared_log_blob_survives_until_last_reference_is_gone(make_env, tmp_path):  # noqa: F811
    env = make_env([BOUNDARY, BOUNDARY])
    first = run(env, "boundary_bug", tmp_path)
    second = run(env, "boundary_bug", tmp_path)  # identical output -> same content-addressed blob
    with session_scope(env.deps.engine) as s:
        refs = {r.stdout_ref for r in s.scalars(select(ExecutionResult)) if r.stdout_ref}
    c = TestClient(create_app(env.deps.settings, env.deps.engine))
    assert c.delete(f"/api/investigations/{first.investigation_id}").status_code == 204
    for key in refs:
        if any(r.stdout_ref == key for r in _all_runs(env)):
            env.deps.blobs.path(key)  # still referenced by the second investigation
    assert c.delete(f"/api/investigations/{second.investigation_id}").status_code == 204
    for key in refs:
        with pytest.raises(FileNotFoundError):
            env.deps.blobs.path(key)


def _all_runs(env):
    with session_scope(env.deps.engine) as s:
        return list(s.scalars(select(ExecutionResult)))


def test_purge_deletes_only_old_finished_investigations(make_env, tmp_path):  # noqa: F811
    env = make_env([BOUNDARY])
    old = run(env, "boundary_bug", tmp_path).investigation_id
    recent_running = seed(env, "no_bug", tmp_path)
    old_running = seed(env, "exception_bug", tmp_path)
    with session_scope(env.deps.engine) as s:
        for inv_id in (old, old_running):
            s.get(Investigation, inv_id).created_at = datetime.now(UTC) - timedelta(days=45)
    result = purge_older_than(env.deps.engine, env.deps.blobs, days=30)
    assert result["investigations"] == 1
    with session_scope(env.deps.engine) as s:
        remaining = {i.id for i in s.scalars(select(Investigation))}
    assert remaining == {recent_running, old_running}  # unfinished work is never purged


def test_blob_store_rejects_keys_that_could_escape_the_store(tmp_path):
    from redfirst.storage.blobs import BlobStore

    store = BlobStore(tmp_path / "blobs")
    for bad in ["../../etc/passwd", "a" * 63, "A" * 64, "../" + "a" * 61, "", "a/b"]:
        with pytest.raises(ValueError):
            store.path(bad)
        with pytest.raises(ValueError):
            store.delete(bad)


