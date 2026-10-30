"""Build the hardened ``docker run`` argument list. Pure function: easy to review and test."""

from dataclasses import dataclass
from pathlib import Path

CONTAINER_REPO = "/repo"
CONTAINER_GEN = "/gen"
CONTAINER_PLUGIN = "/plugin"
CONTAINER_OUT = "/out"


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    name: str
    repo_dir: Path  # extracted repository, mounted read-only
    gen_dir: Path  # directory holding the generated test file, read-only
    plugin_dir: Path  # directory holding collector_plugin.py, read-only
    out_dir: Path  # the only writable bind mount: receives the JSON report
    test_file: str = "test_redfirst.py"
    source_roots: tuple[str, ...] = (".",)
    memory: str = "512m"
    cpus: str = "1"
    pids_limit: int = 128
    tmpfs_size: str = "64m"
    uid: int = 10001


def build_docker_args(spec: SandboxSpec) -> list[str]:
    pythonpath = ":".join(
        [CONTAINER_PLUGIN] + [f"{CONTAINER_REPO}/{r}".rstrip("/.") or CONTAINER_REPO
                              for r in spec.source_roots]
    )
    # No --rm: the runner must read the exit code and OOM flag from the stopped container
    # before removing it itself (sandbox/runner.py).
    return [
        "docker", "run", "--name", spec.name,
        "--network", "none",
        "--read-only",
        "--tmpfs", f"/tmp:rw,noexec,nosuid,size={spec.tmpfs_size}",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", f"{spec.uid}:{spec.uid}",
        "--memory", spec.memory, "--memory-swap", spec.memory,
        "--cpus", spec.cpus,
        "--pids-limit", str(spec.pids_limit),
        "--ulimit", "nofile=256:256",
        "--ulimit", "fsize=10000000",
        "-v", f"{spec.repo_dir}:{CONTAINER_REPO}:ro",
        "-v", f"{spec.gen_dir}:{CONTAINER_GEN}:ro",
        "-v", f"{spec.plugin_dir}:{CONTAINER_PLUGIN}:ro",
        "-v", f"{spec.out_dir}:{CONTAINER_OUT}:rw",
        "-e", f"PYTHONPATH={pythonpath}",
        "-e", f"REDFIRST_REPORT_PATH={CONTAINER_OUT}/report.json",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-w", CONTAINER_REPO,
        spec.image,
        "python", "-m", "pytest", f"{CONTAINER_GEN}/{spec.test_file}",
        "-p", "collector_plugin", "-p", "no:cacheprovider",
        "--rootdir", CONTAINER_GEN, "-q", "--tb=short", "--no-header",
    ]
