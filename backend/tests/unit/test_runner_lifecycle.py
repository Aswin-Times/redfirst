"""D9: container lifecycle of the Docker runner, against a FAKE Docker CLI.

These tests check the runner's control flow (create, wait, inspect, kill, remove) using a stand-in
that implements the documented semantics of the docker CLI commands the runner uses, e.g. that
``--rm`` deletes a container as soon as it exits. They do NOT verify Docker or isolation; that is
tests/integration/test_sandbox_docker.py, run by .github/workflows/sandbox.yml.
"""

import json
import os
import subprocess
import sys

import pytest

from redfirst.domain.enums import OutcomeReason as R
from redfirst.sandbox import runner
from redfirst.sandbox.executor import PLUGIN_DIR
from redfirst.verification.models import FailureSignature, TestContract
from redfirst.verification.rules import classify

CONTRACT = TestContract(target_modules=["app/users.py"],
                        expected_signature=FailureSignature(exception_type="KeyError"),
                        has_control_test=True, exercises_target=True)
PASSED = {"setup": {"outcome": "passed"}, "call": {"outcome": "passed"},
          "teardown": {"outcome": "passed"}}
GOOD_REPORT = {"exitstatus": 0, "collection_errors": [], "tests": {
    "test_redfirst.py::test_reproduces_bug": {"phases": PASSED},
    "test_redfirst.py::test_control": {"phases": PASSED}}}


class FakeDocker:
    """Implements the docker CLI subcommands the runner uses, with Docker's semantics."""

    def __init__(self, *, exit_code=0, oom=False, never_starts=False, hangs=False,
                 report=None, inspect_fails=False):
        self.exit_code, self.oom = exit_code, oom
        self.never_starts, self.hangs, self.report = never_starts, hangs, report
        self.inspect_fails = inspect_fails
        self.containers: dict[str, dict] = {}
        self.calls: list[list[str]] = []

    @staticmethod
    def _done(args, code=0, out=b"", err=b"", text=False):
        if text:
            out, err = out.decode(), err.decode()
        return subprocess.CompletedProcess(args, code, out, err)

    def __call__(self, args, capture_output=True, timeout=None, check=False, text=False, **_):
        self.calls.append(list(args))
        cmd, rest = args[1], args[2:]
        if cmd == "info":
            return self._done(args, 0, text=text)
        if cmd == "run":
            name = rest[rest.index("--name") + 1]
            if self.never_starts:
                return self._done(args, 125, err=b"Unable to find image 'missing:tag'", text=text)
            self.containers[name] = {"Status": "running", "Running": True, "OOMKilled": False,
                                     "ExitCode": 0, "StartedAt": "2026-10-30T10:00:00Z"}
            out_mount = next(v for v in rest if v.endswith(":/out:rw"))
            out_dir = out_mount[: -len(":/out:rw")]
            if self.report is not None:
                with open(os.path.join(out_dir, "report.json"), "w") as fh:
                    json.dump(self.report, fh)
            if self.hangs:
                raise subprocess.TimeoutExpired(args, timeout, output=b"partial", stderr=b"")
            self.containers[name].update(Status="exited", Running=False, OOMKilled=self.oom,
                                         ExitCode=self.exit_code)
            if "--rm" in rest:  # Docker removes the container as soon as it exits
                del self.containers[name]
            return self._done(args, self.exit_code, out=b"test output", text=text)
        name = rest[-1]
        if cmd == "inspect":
            if self.inspect_fails or name not in self.containers:
                return self._done(args, 1, err=b"Error: No such object", text=text)
            state = self.containers[name]
            if "{{json .State}}" in rest:
                return self._done(args, 0, out=json.dumps(state).encode(), text=text)
            if "{{.State.OOMKilled}}" in rest:
                return self._done(args, 0, out=str(state["OOMKilled"]).lower().encode(),
                                  text=text)
        if cmd == "kill" and name in self.containers:
            self.containers[name].update(Status="exited", Running=False, ExitCode=137)
            return self._done(args, 0, text=text)
        if cmd == "wait":
            code = self.containers.get(name, {}).get("ExitCode", 0)
            return self._done(args, 0, out=f"{code}\n".encode(), text=text)
        if cmd == "rm":
            self.containers.pop(name, None)
            return self._done(args, 0, text=text)
        return self._done(args, 1, err=b"unsupported", text=text)

    def ran(self, cmd: str) -> bool:
        return any(c[1] == cmd for c in self.calls)


@pytest.fixture
def fake(monkeypatch):
    def install(**kw) -> FakeDocker:
        docker = FakeDocker(**kw)
        monkeypatch.setattr(runner.subprocess, "run", docker)
        monkeypatch.setattr(runner.shutil, "which", lambda _: "/usr/bin/docker")
        return docker
    return install


def run(tmp_path, **kw):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return runner.run_test_in_sandbox(image="img", repo_dir=repo, test_code="def test(): pass\n",
                                      plugin_dir=PLUGIN_DIR, work_dir=tmp_path / "work", **kw)


def test_oom_kill_is_read_from_the_container_before_it_is_removed(fake, tmp_path):
    docker = fake(exit_code=137, oom=True)
    out = run(tmp_path)
    assert out.result.oom_killed
    assert classify([out.result], CONTRACT).reason is R.RESOURCE_LIMIT
    assert docker.containers == {} and docker.ran("rm")


def test_run_does_not_ask_docker_to_auto_remove(fake, tmp_path):
    docker = fake(report=GOOD_REPORT)
    run(tmp_path)
    run_args = next(c for c in docker.calls if c[1] == "run")
    assert "--rm" not in run_args


def test_successful_run_uses_the_runtime_exit_code_and_cleans_up(fake, tmp_path):
    docker = fake(exit_code=0, report=GOOD_REPORT)
    out = run(tmp_path)
    assert out.exit_code == 0 and out.result.exit_code == 0
    assert out.result.integrity_errors == [] and not out.result.runner_crashed
    assert docker.containers == {} and out.container_removed


def test_failing_run_cleans_up(fake, tmp_path):
    docker = fake(exit_code=1, report=None)
    out = run(tmp_path)
    assert out.result.integrity_errors  # no report although the process ran: untrusted
    assert docker.containers == {}


def test_timeout_kills_inspects_and_removes_the_container(fake, tmp_path):
    docker = fake(hangs=True)
    out = run(tmp_path, timeout_seconds=1)
    assert out.result.timed_out
    assert docker.ran("kill") and docker.containers == {}
    assert classify([out.result], CONTRACT).reason is R.RESOURCE_LIMIT


def test_container_that_never_started_is_a_runner_failure_with_dockers_message(fake, tmp_path):
    fake(never_starts=True)
    out = run(tmp_path)
    assert out.result.runner_crashed
    assert "Unable to find image" in (out.result.runner_error or "")


def test_process_exiting_125_after_starting_is_not_mistaken_for_a_docker_failure(fake, tmp_path):
    fake(exit_code=125, report=None)  # the test process itself chose exit code 125
    out = run(tmp_path)
    assert not out.result.runner_crashed
    assert classify([out.result], CONTRACT).reason is R.INVALID_REPORT


def test_inspect_failure_is_a_runner_failure_and_still_cleans_up(fake, tmp_path):
    docker = fake(exit_code=0, report=GOOD_REPORT, inspect_fails=True)
    out = run(tmp_path)
    assert out.result.runner_crashed and docker.ran("rm")


def test_docker_missing_raises_sandbox_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.shutil, "which", lambda _: None)
    with pytest.raises(runner.SandboxUnavailable):
        run(tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_output_dir_is_writable_by_the_container_user_but_private_on_the_host(fake, tmp_path):
    fake(report=GOOD_REPORT)
    run(tmp_path)
    work = tmp_path / "work"
    assert (work.stat().st_mode & 0o777) == 0o700
    assert (work / "out").stat().st_mode & 0o777 == 0o777
