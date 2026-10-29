"""Run a generated test in a hardened Docker container and return structured facts.

The wall-clock timeout is enforced here, outside the container, and the container is always
force-removed afterwards. NOTE: this module has not yet been exercised against a real Docker
daemon (none on the dev machine); see tests/integration/test_sandbox_docker.py.
"""

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from redfirst.sandbox.docker_cmd import SandboxSpec, build_docker_args
from redfirst.sandbox.results import build_run_result
from redfirst.verification.models import RunResult

MAX_OUTPUT_BYTES = 256 * 1024
_OOM_EXIT_CODE = 137  # SIGKILL; combined with an inspect check below


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


def _force_remove(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30, check=False)


def _oom_killed(name: str) -> bool:
    proc = subprocess.run(["docker", "inspect", "-f", "{{.State.OOMKilled}}", name],
                          capture_output=True, text=True, timeout=15, check=False)
    return proc.stdout.strip() == "true"


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

    gen_dir, out_dir = work_dir / "gen", work_dir / "out"
    gen_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "test_redfirst.py").write_text(test_code, encoding="utf-8")

    name = f"redfirst-{uuid.uuid4().hex[:12]}"
    spec = SandboxSpec(
        image=image, name=name, repo_dir=repo_dir.resolve(), gen_dir=gen_dir.resolve(),
        plugin_dir=plugin_dir.resolve(), out_dir=out_dir.resolve(),
        source_roots=source_roots, memory=memory,
    )
    started = time.monotonic()
    timed_out = oom = False
    exit_code: int | None = None
    stdout = stderr = b""
    try:
        proc = subprocess.run(build_docker_args(spec), capture_output=True,
                              timeout=timeout_seconds, check=False)
        exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        oom = exit_code == _OOM_EXIT_CODE and _oom_killed(name)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
    finally:
        _force_remove(name)  # also terminates a still-running container after a timeout
    duration_ms = int((time.monotonic() - started) * 1000)

    report = None
    report_path = out_dir / "report.json"
    if report_path.is_file() and report_path.stat().st_size <= MAX_OUTPUT_BYTES * 4:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = None  # recorded as report_parsed=False, never swallowed into a verdict

    # Exit code 125-127 means docker itself failed to start the container.
    crashed = exit_code in (125, 126, 127) and report is None
    result = build_run_result(report, timed_out=timed_out, oom_killed=oom, runner_crashed=crashed)
    out, t1 = _clip(stdout)
    err, t2 = _clip(stderr)
    return SandboxRun(result, exit_code, duration_ms, out, err, t1 or t2)
