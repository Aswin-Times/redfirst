"""The execution seam used by the orchestrator. Production uses Docker."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from redfirst.sandbox import collector_plugin
from redfirst.sandbox.runner import SandboxRun, run_test_in_sandbox

PLUGIN_DIR = Path(collector_plugin.__file__).resolve().parent


@dataclass(frozen=True)
class ExecRequest:
    repo_dir: Path
    test_code: str
    work_dir: Path  # fresh, per run
    source_roots: tuple[str, ...]


class Executor(Protocol):
    def __call__(self, request: ExecRequest) -> SandboxRun: ...


@dataclass(frozen=True)
class DockerExecutor:
    image: str
    timeout_seconds: int
    memory: str

    def __call__(self, request: ExecRequest) -> SandboxRun:
        return run_test_in_sandbox(
            image=self.image, repo_dir=request.repo_dir, test_code=request.test_code,
            plugin_dir=PLUGIN_DIR, work_dir=request.work_dir,
            source_roots=request.source_roots, timeout_seconds=self.timeout_seconds,
            memory=self.memory,
        )
