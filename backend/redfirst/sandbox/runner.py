"""Run a generated test in a hardened Docker container and return structured facts.

Lifecycle: the container is started *without* ``--rm``. After the process exits, or is killed
when the wall-clock timeout (enforced here, outside the container) expires, the runner reads
authoritative state from the container runtime -- exit code, OOM kill, whether it ever started --
and only then removes the container. Removal happens on every path, including errors.

The exit code and OOM flag come from Docker, not from anything the test process wrote; they
are what the report is cross-checked against (see sandbox/results.py).

NOTE: the control flow is unit-tested against a fake docker CLI. Real Docker behaviour is
covered only by tests/integration/test_sandbox_docker.py (CI: .github/workflows/sandbox.yml).
"""

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redfirst.sandbox.docker_cmd import (
    CONTAINER_GEN,
    CONTAINER_REPO,
    SandboxSpec,
    build_docker_args,
)
from redfirst.sandbox.results import GENERATED_TEST_FILE, build_run_result, read_report
from redfirst.verification.models import RunResult

log = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 256 * 1024
REPORT_FILE = "report.json"
_HOUSEKEEPING_TIMEOUT = 30  # seconds for inspect / kill / wait / rm


class SandboxUnavailable(RuntimeError):
    """Docker is missing or its daemon is unreachable (an infrastructure problem)."""


@dataclass(frozen=True)
class SandboxRun:
    result: RunResult
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    output_truncated: bool
    container_name: str | None = None
    container_removed: bool | None = None  # None when no container was involved


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _clip(data: bytes) -> tuple[str, bool]:
    return data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"), len(data) > MAX_OUTPUT_BYTES


def _docker(*args: str) -> subprocess.CompletedProcess[bytes] | None:
    """Run a housekeeping docker command; None if it could not be run at all."""
    try:
        return subprocess.run(["docker", *args], capture_output=True,
                              timeout=_HOUSEKEEPING_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("docker %s failed: %s", args[0], exc)
        return None


def _inspect_state(name: str) -> dict[str, Any] | None:
    proc = _docker("inspect", "--format", "{{json .State}}", name)
    if proc is None or proc.returncode != 0:
        return None
    try:
        state = json.loads(proc.stdout.decode("utf-8", errors="replace") or "null")
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def _started(state: dict[str, Any]) -> bool:
    return not str(state.get("StartedAt") or "0001-01-01").startswith("0001-01-01")


def _kill(name: str) -> None:
    _docker("kill", name)
    _docker("wait", name)  # make sure it has stopped before its state is read


def _remove(name: str) -> bool:
    proc = _docker("rm", "--force", "--volumes", name)
    removed = proc is not None and proc.returncode == 0
    if not removed:
        log.warning("could not remove container %s; it may need manual cleanup", name)
    return removed


def _prepare(work_dir: Path) -> tuple[Path, Path]:
    """Create the run directories with permissions that work for the container user.

    The container runs as an unprivileged uid that does not own these host directories. The
    output directory must be writable by it, so it is world-writable; the enclosing run
    directory is private to the worker, so other host users cannot reach it. (Inside the
    container only the bind-mounted directory itself is visible, not its host parents.)
    """
    gen_dir, out_dir = work_dir / "gen", work_dir / "out"
    for path in (work_dir, gen_dir, out_dir):
        path.mkdir(parents=True, exist_ok=True)
    os.chmod(work_dir, 0o700)
    os.chmod(gen_dir, 0o755)
    os.chmod(out_dir, 0o777)
    return gen_dir, out_dir


def run_test_in_sandbox(
    *,
    image: str,
    repo_dir: Path,
    test_code: str,
    plugin_dir: Path,
    work_dir: Path,
    source_roots: tuple[str, ...] = (".",),
    timeout_seconds: int = 60,
    memory: str = "512m",
) -> SandboxRun:
    """Execute ``test_code`` against ``repo_dir``. Raises SandboxUnavailable if Docker is down."""
    if not docker_available():
        raise SandboxUnavailable("docker is not installed or the daemon is not reachable")

    gen_dir, out_dir = _prepare(work_dir)
    test_path = gen_dir / GENERATED_TEST_FILE
    test_path.write_text(test_code, encoding="utf-8")
    os.chmod(test_path, 0o644)

    name = f"redfirst-{uuid.uuid4().hex[:12]}"
    spec = SandboxSpec(
        image=image, name=name, repo_dir=repo_dir.resolve(), gen_dir=gen_dir.resolve(),
        plugin_dir=plugin_dir.resolve(), out_dir=out_dir.resolve(),
        source_roots=source_roots, memory=memory,
    )
    started = time.monotonic()
    timed_out = False
    cli_exit: int | None = None
    stdout = stderr = b""
    state: dict[str, Any] | None = None
    removed = False
    try:
        try:
            proc = subprocess.run(build_docker_args(spec), capture_output=True,
                                  timeout=timeout_seconds, check=False)
            cli_exit, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout, stderr = exc.stdout or b"", exc.stderr or b""
            _kill(name)
        state = _inspect_state(name)
    finally:
        removed = _remove(name)
    duration_ms = int((time.monotonic() - started) * 1000)

    out, t1 = _clip(stdout)
    err, t2 = _clip(stderr)
    if state is None or not _started(state):
        detail = err.strip()[:300] or "no error output"
        reason = ("the container runtime reported no state for the container" if
                  cli_exit is not None and state is None and cli_exit not in (125, 126, 127)
                  else "docker could not start the container")
        result = build_run_result(None, runner_crashed=True,
                                  runner_error=f"{reason} (docker exit {cli_exit}): {detail}")
        return SandboxRun(result, cli_exit, duration_ms, out, err, t1 or t2, name, removed)

    exit_code = state.get("ExitCode")
    exit_code = exit_code if isinstance(exit_code, int) else None
    report, problem = read_report(out_dir / REPORT_FILE)
    result = build_run_result(
        report, report_problem=problem, exit_code=exit_code, timed_out=timed_out,
        oom_killed=bool(state.get("OOMKilled")), repo_root=CONTAINER_REPO,
        test_file=f"{CONTAINER_GEN}/{GENERATED_TEST_FILE}",
    )
    return SandboxRun(result, exit_code, duration_ms, out, err, t1 or t2, name, removed)
