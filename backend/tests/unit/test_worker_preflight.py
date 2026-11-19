"""The worker checks it can actually run investigations before it claims any.

Without these checks a worker started on a machine with no Docker claims every queued
investigation and fails it, which looks like REDFIRST is broken. Refusing to start leaves them
queued until a worker that can run them comes along.
"""

import pytest

from redfirst.core.config import Settings
from redfirst.worker import __main__ as worker


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return Settings(llm_api_key="test-key-not-real", sandbox_image="redfirst-sandbox-python:3.12")


def stub(monkeypatch, docker: bool, image: bool):
    monkeypatch.setattr(worker, "docker_available", lambda: docker)
    monkeypatch.setattr(worker, "sandbox_image_available", lambda name: image)


def test_ready_machine_has_no_problems(monkeypatch, settings):
    stub(monkeypatch, docker=True, image=True)
    assert worker.preflight(settings) == ([], [])


def test_missing_docker_is_a_blocking_problem_that_says_what_to_do(monkeypatch, settings):
    stub(monkeypatch, docker=False, image=False)
    problems, _ = worker.preflight(settings)
    assert len(problems) == 1  # no point checking the image without Docker
    assert "Docker is not available" in problems[0]
    assert "stay queued" in problems[0]


def test_missing_sandbox_image_says_how_to_build_it(monkeypatch, settings):
    stub(monkeypatch, docker=True, image=False)
    problems, _ = worker.preflight(settings)
    assert problems == [
        "Sandbox image redfirst-sandbox-python:3.12 not found. Build it from the repository root: "
        "docker build -t redfirst-sandbox-python:3.12 sandbox-images/python"
    ]


def test_missing_api_key_is_a_warning_not_a_blocker(monkeypatch, settings):
    # The SDK can also find credentials in an `ant auth login` profile, so only warn.
    stub(monkeypatch, docker=True, image=True)
    problems, warnings = worker.preflight(Settings(llm_api_key=None))
    assert problems == []
    assert len(warnings) == 1 and "API key" in warnings[0]


def test_api_key_from_the_environment_counts(monkeypatch):
    stub(monkeypatch, docker=True, image=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    assert worker.preflight(Settings(llm_api_key=None)) == ([], [])


def test_main_exits_before_claiming_anything_when_docker_is_missing(monkeypatch, settings, caplog):
    stub(monkeypatch, docker=False, image=False)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["redfirst.worker", "--once"])

    def must_not_run(*args, **kwargs):
        raise AssertionError("the worker claimed work although it cannot run it")

    monkeypatch.setattr(worker, "run_one", must_not_run)
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 2
    assert "Docker is not available" in caplog.text


def test_problems_never_include_the_key_itself(monkeypatch):
    stub(monkeypatch, docker=False, image=False)
    problems, warnings = worker.preflight(Settings(llm_api_key="sk-ant-secret-value-123"))
    assert "sk-ant-secret-value-123" not in " ".join(problems + warnings)
