"""D9 + M9.1 R3: container lifecycle of the Docker runner, against a FAKE Docker CLI.

These tests check the runner's control flow (create, capture, inspect, kill, remove) using a
stand-in that implements the documented semantics of the docker CLI commands the runner uses.
They do NOT verify Docker or isolation; that is tests/integration/test_sandbox_docker.py, run by
.github/workflows/sandbox.yml.
"""

import json
import re
import subprocess

import pytest

from redfirst.domain.enums import OutcomeReason as R
from redfirst.sandbox import runner
from redfirst.sandbox.executor import PLUGIN_DIR
from redfirst.sandbox.results import REPORT_BEGIN, REPORT_END
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


def report_block(report: dict, nonce: str) -> bytes:
    return (f"\n{REPORT_BEGIN.format(nonce=nonce)}\n{json.dumps(report)}\n"
            f"{REPORT_END.format(nonce=nonce)}\n").encode()


class FakeDocker:
    """Implements the docker CLI subcommands the runner uses, with Docker's semantics."""

    def __init__(self, *, exit_code=0, oom=False, never_starts=False, hangs=False,
                 flood=False, report=None, inspect_fails=False, extra_stdout=b""):
        self.exit_code, self.oom = exit_code, oom
        self.never_starts, self.hangs, self.flood, self.report = never_starts, hangs, flood, report
        self.inspect_fails = inspect_fails
        self.extra_stdout = extra_stdout
        self.containers: dict[str, dict] = {}
        self.calls: list[list[str]] = []
        self.run_args: list[str] = []

    @staticmethod
    def _done(args, code=0, out=b"", err=b"", text=False):
        if text:
            out, err = out.decode(), err.decode()
        return subprocess.CompletedProcess(args, code, out, err)

    # The main `docker run`: the runner calls run_bounded for it.
    def run_bounded(self, args, timeout, **_):
        self.calls.append(list(args))
        self.run_args = list(args)
        name = args[args.index("--name") + 1]
        nonce = re.search(r"REDFIRST-REPORT-BEGIN ([0-9a-f]{32})", " ".join(args)).group(1)
        if self.never_starts:
            return runner.Captured(125, b"", b"Unable to find image 'missing:tag'")
        self.containers[name] = {"Status": "running", "Running": True, "OOMKilled": False,
                                 "ExitCode": 0, "StartedAt": "2026-10-30T10:00:00Z"}
        if self.hangs:
            return runner.Captured(None, b"partial", b"", timed_out=True)
        self.containers[name].update(Status="exited", Running=False, OOMKilled=self.oom,
                                     ExitCode=self.exit_code)
        if self.flood:
            return runner.Captured(137, b"x" * 100, b"", flooded=True, truncated=True)
        out = b"test output" + self.extra_stdout
        if self.report is not None:
            out += report_block(self.report, nonce)
        return runner.Captured(self.exit_code, out, b"")

    def __call__(self, args, capture_output=True, timeout=None, check=False, text=False, **_):
        self.calls.append(list(args))
        cmd, rest = args[1], args[2:]
        if cmd == "info":
            return self._done(args, 0, text=text)
        name = rest[-1]
        if cmd == "inspect":
            if self.inspect_fails or name not in self.containers:
                return self._done(args, 1, err=b"Error: No such object", text=text)
            return self._done(args, 0, out=json.dumps(self.containers[name]).encode(), text=text)
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
        return any(len(c) > 1 and c[1] == cmd for c in self.calls)


@pytest.fixture
def fake(monkeypatch):
    def install(**kw) -> FakeDocker:
        docker = FakeDocker(**kw)
        monkeypatch.setattr(runner.subprocess, "run", docker)
        monkeypatch.setattr(runner, "run_bounded", docker.run_bounded)
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
    assert "--rm" not in docker.run_args


def test_successful_run_reads_the_report_from_the_output_and_the_exit_code_from_docker(
        fake, tmp_path):
    docker = fake(exit_code=0, report=GOOD_REPORT)
    out = run(tmp_path)
    assert out.exit_code == 0 and out.result.exit_code == 0
    assert out.result.integrity_errors == [] and not out.result.runner_crashed
    assert "REDFIRST-REPORT" not in out.stdout and "test output" in out.stdout  # block stripped
    assert docker.containers == {} and out.container_removed


def test_report_block_with_the_wrong_nonce_is_not_used(fake, tmp_path):
    fake(exit_code=0, report=None,
         extra_stdout=report_block(GOOD_REPORT, "f" * 32))  # attacker guessed a nonce
    out = run(tmp_path)
    assert out.result.integrity_errors and "no report block" in out.result.integrity_errors[0]
    assert classify([out.result], CONTRACT).reason is R.INVALID_REPORT


def test_failing_run_without_a_report_is_untrusted_and_cleans_up(fake, tmp_path):
    docker = fake(exit_code=1, report=None)
    out = run(tmp_path)
    assert out.result.integrity_errors
    assert docker.containers == {}


def test_nothing_is_created_on_the_host_for_the_container_to_write(fake, tmp_path):
    fake(report=GOOD_REPORT)
    run(tmp_path)
    assert sorted(p.name for p in (tmp_path / "work").iterdir()) == ["gen"]


def test_output_flood_stops_the_container_and_is_a_resource_limit(fake, tmp_path):
    docker = fake(flood=True)
    out = run(tmp_path)
    assert out.result.output_flooded and out.output_truncated
    assert docker.ran("kill") and docker.containers == {}
    assert classify([out.result], CONTRACT).reason is R.RESOURCE_LIMIT


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


def test_exception_while_running_still_removes_the_container(fake, tmp_path, monkeypatch):
    docker = fake(report=GOOD_REPORT)

    def boom(*a, **k):
        docker.containers["x"] = {"Status": "running"}
        raise RuntimeError("worker interrupted")

    monkeypatch.setattr(runner, "run_bounded", boom)
    with pytest.raises(RuntimeError):
        run(tmp_path)
    assert docker.ran("rm")


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX permissions only")
def test_run_directory_is_private_and_the_test_directory_readable_by_the_container_user(
        fake, tmp_path):
    fake(report=GOOD_REPORT)
    run(tmp_path)
    work = tmp_path / "work"
    assert (work.stat().st_mode & 0o777) == 0o700
    assert (work / "gen").stat().st_mode & 0o777 == 0o755
    assert (work / "gen" / "test_redfirst.py").stat().st_mode & 0o777 == 0o644
