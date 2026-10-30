"""Build the hardened ``docker run`` argument list. Pure function: easy to review and test."""

from dataclasses import dataclass
from pathlib import Path

from redfirst.sandbox.results import REPORT_BEGIN, REPORT_END

CONTAINER_REPO = "/repo"
CONTAINER_GEN = "/gen"
CONTAINER_PLUGIN = "/plugin"
CONTAINER_OUT = "/out"

# Runs inside the container as PID 1, after pytest has exited. It:
#   1. keeps pytest's exit status,
#   2. kills every other process, so nothing the tests started can print after this point,
#   3. prints the report between this run's nonce markers (the host takes the last block),
#   4. exits with pytest's status, which Docker then records as the container's exit code.
# The report lives on a small tmpfs, so nothing is written to the host and nothing the
# container writes can fill a host disk. Only constants and the nonce appear in the script;
# the pytest command arrives as separate arguments ("$@").
WRAPPER = (
    'status=0; "$@" || status=$?; '
    'python -P -c "import os, signal; os.kill(-1, signal.SIGKILL)" 2>/dev/null; '
    "printf '\\n%s\\n' '" + REPORT_BEGIN + "'; "
    "cat /out/report.json 2>/dev/null; "
    "printf '\\n%s\\n' '" + REPORT_END + "'; "
    'exit "$status"'
)


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    name: str
    repo_dir: Path  # extracted repository, mounted read-only
    gen_dir: Path  # directory holding the generated test file, read-only
    plugin_dir: Path  # directory holding collector_plugin.py, read-only
    nonce: str  # random per run; tags the report block in the container's output
    test_file: str = "test_redfirst.py"
    source_roots: tuple[str, ...] = (".",)
    memory: str = "512m"
    cpus: str = "1"
    pids_limit: int = 128
    tmpfs_size: str = "64m"
    out_tmpfs_size: str = "2m"  # the report area; also a ceiling on what /out can hold
    uid: int = 10001


def build_docker_args(spec: SandboxSpec) -> list[str]:
    # Repository roots are NOT put on PYTHONPATH: PYTHONPATH entries precede the standard
    # library, so a repository file such as types.py or re.py would replace the stdlib module
    # pytest itself imports. The collector plugin appends these roots to sys.path instead
    # (after the stdlib and site-packages), and `python -P` keeps the working directory off it.
    source_roots = ":".join(
        f"{CONTAINER_REPO}/{r}".rstrip("/.") or CONTAINER_REPO for r in spec.source_roots
    )
    script = WRAPPER.format(nonce=spec.nonce)
    # No --rm: the runner must read the exit code and OOM flag from the stopped container
    # before removing it itself (sandbox/runner.py).
    return [
        "docker", "run", "--name", spec.name,
        "--network", "none",
        "--read-only",
        "--tmpfs", f"/tmp:rw,noexec,nosuid,size={spec.tmpfs_size}",
        "--tmpfs", f"{CONTAINER_OUT}:rw,noexec,nosuid,size={spec.out_tmpfs_size},mode=1777",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", f"{spec.uid}:{spec.uid}",
        "--memory", spec.memory, "--memory-swap", spec.memory,
        "--cpus", spec.cpus,
        "--pids-limit", str(spec.pids_limit),
        "--ulimit", "nofile=256:256",
        "--ulimit", "fsize=10000000",
        # Docker keeps container output in a host log file; cap it (the runner also reads the
        # output through a bounded buffer and stops runs that print more than its hard cap).
        "--log-driver", "json-file", "--log-opt", "max-size=1m", "--log-opt", "max-file=1",
        "-v", f"{spec.repo_dir}:{CONTAINER_REPO}:ro",
        "-v", f"{spec.gen_dir}:{CONTAINER_GEN}:ro",
        "-v", f"{spec.plugin_dir}:{CONTAINER_PLUGIN}:ro",
        "-e", f"PYTHONPATH={CONTAINER_PLUGIN}",
        "-e", f"REDFIRST_SOURCE_ROOTS={source_roots}",
        "-e", f"REDFIRST_REPORT_PATH={CONTAINER_OUT}/report.json",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-w", CONTAINER_REPO,
        spec.image,
        "sh", "-c", script, "redfirst-run",
        "python", "-P", "-m", "pytest", f"{CONTAINER_GEN}/{spec.test_file}",
        "-p", "collector_plugin", "-p", "no:cacheprovider",
        "--rootdir", CONTAINER_GEN, "-q", "--tb=short", "--no-header",
    ]
