"""Run a generated test in a hardened Docker container and return structured facts.

Lifecycle: the container is started *without* ``--rm``. After the process exits, or is killed
when the wall-clock timeout (enforced here, outside the container) expires, the runner reads
authoritative state from the container runtime -- exit code, OOM kill, whether it ever started --
and only then removes the container. Removal happens on every path, including errors.

The exit code and OOM flag come from Docker, not from anything the test process wrote; they
are what the report is cross-checked against (see sandbox/results.py). Output is read through
bounded buffers, and the report arrives as a nonce-tagged block in that output: no host
directory is writable by the container.

NOTE: the control flow is unit-tested against a fake docker CLI. Real Docker behaviour is
covered only by tests/integration/test_sandbox_docker.py (CI: .github/workflows/sandbox.yml).
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from redfirst.sandbox.docker_cmd import (
    CONTAINER_GEN,
    CONTAINER_REPO,
    SandboxSpec,
    build_docker_args,
)
from redfirst.sandbox.results import (
    GENERATED_TEST_FILE,
    build_run_result,
    decode_report,
    extract_report_block,
    strip_report_block,
)
from redfirst.verification.models import RunResult

log = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 256 * 1024  # what is stored and shown per stream
CAPTURE_HEAD_BYTES = 192 * 1024
CAPTURE_TAIL_BYTES = 512 * 1024  # must hold the whole report block, which is printed last
HARD_OUTPUT_CAP_BYTES = 64 * 1024 * 1024  # a run that prints more than this is stopped
_TRUNCATION_NOTE = b"\n[... output truncated by REDFIRST ...]\n"
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


def sandbox_image_available(image: str) -> bool:
    """Whether the sandbox image has been built on this Docker host."""
    try:
        proc = subprocess.run(["docker", "image", "inspect", image], capture_output=True,
                              timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


@dataclass(frozen=True)
class Captured:
    """Result of running a process with bounded output capture."""

    returncode: int | None  # None when the run timed out
    stdout: bytes  # head + tail of the stream, with a note where bytes were dropped
    stderr: bytes
    timed_out: bool = False
    flooded: bool = False  # stopped because the output exceeded the hard cap
    truncated: bool = False  # some output was dropped


class _Bounded:
    """Keeps the first ``head`` and last ``tail`` bytes of a stream, whatever its length."""

    def __init__(self, head: int, tail: int) -> None:
        self.head_max, self.tail_max = head, tail
        self.head = bytearray()
        self.tail = bytearray()
        self.truncated = False

    def feed(self, data: bytes) -> None:
        if len(self.head) < self.head_max:
            take = data[: self.head_max - len(self.head)]
            self.head += take
            data = data[len(take):]
        if data:
            self.tail += data
            if len(self.tail) > self.tail_max:
                del self.tail[: len(self.tail) - self.tail_max]
                self.truncated = True

    def value(self) -> bytes:
        if self.truncated:
            return bytes(self.head) + _TRUNCATION_NOTE + bytes(self.tail)
        return bytes(self.head) + bytes(self.tail)


def run_bounded(
    args: list[str],
    timeout: float,
    head_bytes: int = CAPTURE_HEAD_BYTES,
    tail_bytes: int = CAPTURE_TAIL_BYTES,
    hard_cap_bytes: int = HARD_OUTPUT_CAP_BYTES,
) -> Captured:
    """Run ``args`` reading stdout/stderr through bounded buffers.

    ``subprocess.run(capture_output=True)`` buffers everything in memory, so a test that prints
    in a loop could exhaust the worker's RAM. Here memory is bounded by head + tail per stream,
    and the process is killed once the total exceeds ``hard_cap_bytes`` (flooded) or the
    deadline passes (timed_out). Killing the CLI does not stop a container; callers do that.
    """
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    buffers = {"out": _Bounded(head_bytes, tail_bytes), "err": _Bounded(head_bytes, tail_bytes)}
    total = [0]
    lock = threading.Lock()
    flooded = threading.Event()

    def pump(stream: IO[bytes], buf: _Bounded) -> None:
        try:
            while chunk := stream.read1(65536):
                buf.feed(chunk)
                with lock:
                    total[0] += len(chunk)
                    if total[0] > hard_cap_bytes:
                        flooded.set()
        except (OSError, ValueError):  # stream closed under us after a kill
            pass

    threads = [threading.Thread(target=pump, args=(proc.stdout, buffers["out"]), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, buffers["err"]), daemon=True)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while proc.poll() is None:
        if flooded.is_set():
            proc.kill()
            break
        if time.monotonic() > deadline:
            timed_out = True
            proc.kill()
            break
        time.sleep(0.02)
    proc.wait()
    for t in threads:
        t.join(timeout=10)
    for stream in (proc.stdout, proc.stderr):
        try:
            stream.close()
        except OSError:
            pass
    return Captured(
        returncode=None if timed_out else proc.returncode,
        stdout=buffers["out"].value(), stderr=buffers["err"].value(),
        timed_out=timed_out, flooded=flooded.is_set(),
        truncated=buffers["out"].truncated or buffers["err"].truncated,
    )


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


def _prepare(work_dir: Path) -> Path:
    """Create the run directory; returns the (read-only mounted) generated-test directory.

    The container only ever reads from host directories (all mounts are ``:ro``) and writes to
    in-container tmpfs, so nothing it does can create files on the host. The run directory is
    private to the worker; the test directory is world-readable for the container's uid.
    """
    gen_dir = work_dir / "gen"
    for path in (work_dir, gen_dir):
        path.mkdir(parents=True, exist_ok=True)
    os.chmod(work_dir, 0o700)
    os.chmod(gen_dir, 0o755)
    return gen_dir


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

    gen_dir = _prepare(work_dir)
    test_path = gen_dir / GENERATED_TEST_FILE
    test_path.write_text(test_code, encoding="utf-8")
    os.chmod(test_path, 0o644)

    name = f"redfirst-{uuid.uuid4().hex[:12]}"
    nonce = uuid.uuid4().hex
    spec = SandboxSpec(
        image=image, name=name, repo_dir=repo_dir.resolve(), gen_dir=gen_dir.resolve(),
        plugin_dir=plugin_dir.resolve(), nonce=nonce, source_roots=source_roots, memory=memory,
    )
    started = time.monotonic()
    cap = Captured(returncode=None, stdout=b"", stderr=b"")
    state: dict[str, Any] | None = None
    removed = False
    try:
        cap = run_bounded(build_docker_args(spec), timeout_seconds)
        if cap.timed_out or cap.flooded:
            _kill(name)  # stopping the docker CLI does not stop the container
        state = _inspect_state(name)
    finally:
        removed = _remove(name)
    duration_ms = int((time.monotonic() - started) * 1000)

    stdout_text = strip_report_block(cap.stdout.decode("utf-8", errors="replace"), nonce)
    stderr_text = cap.stderr.decode("utf-8", errors="replace")
    clipped = len(stdout_text) > MAX_OUTPUT_BYTES or len(stderr_text) > MAX_OUTPUT_BYTES
    out, err = stdout_text[:MAX_OUTPUT_BYTES], stderr_text[:MAX_OUTPUT_BYTES]
    truncated = cap.truncated or clipped

    if state is None or not _started(state):
        detail = err.strip()[:300] or "no error output"
        reason = ("the container runtime reported no state for the container" if
                  cap.returncode is not None and state is None
                  and cap.returncode not in (125, 126, 127)
                  else "docker could not start the container")
        result = build_run_result(
            None, runner_crashed=True,
            runner_error=f"{reason} (docker exit {cap.returncode}): {detail}")
        return SandboxRun(result, cap.returncode, duration_ms, out, err, truncated, name, removed)

    exit_code = state.get("ExitCode")
    exit_code = exit_code if isinstance(exit_code, int) else None
    report = problem = None
    raw, problem = extract_report_block(cap.stdout, nonce)
    if raw is not None:
        report, problem = decode_report(raw)
    result = build_run_result(
        report, report_problem=problem, exit_code=exit_code, timed_out=cap.timed_out,
        oom_killed=bool(state.get("OOMKilled")), output_flooded=cap.flooded,
        repo_root=CONTAINER_REPO, test_file=f"{CONTAINER_GEN}/{GENERATED_TEST_FILE}",
    )
    return SandboxRun(result, exit_code, duration_ms, out, err, truncated, name, removed)
