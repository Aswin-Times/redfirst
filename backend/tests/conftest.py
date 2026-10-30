"""Shared test helpers.

``local_executor`` runs a generated test with plain pytest in a subprocess. It is NOT a
sandbox and must only ever run the project's own fixture repositories.
"""

import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from redfirst.sandbox.executor import PLUGIN_DIR, ExecRequest
from redfirst.sandbox.results import GENERATED_TEST_FILE, build_run_result, read_report
from redfirst.sandbox.runner import SandboxRun

FIXTURE_REPOS = Path(__file__).resolve().parents[2] / "fixtures" / "repos"

# Only what Python and pytest need to start; never the developer's whole environment, which
# may hold API keys.
_ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
                    "HOME", "USERPROFILE", "USERNAME", "LANG", "LC_ALL")


def local_executor(request: ExecRequest) -> SandboxRun:
    gen, out = request.work_dir / "gen", request.work_dir / "out"
    gen.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    test_file = gen / GENERATED_TEST_FILE
    test_file.write_text(request.test_code, encoding="utf-8")
    repo_root = request.repo_dir.resolve()
    roots = [str((repo_root / r).resolve()) for r in request.source_roots]
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    env.update(PYTHONPATH=os.pathsep.join([str(PLUGIN_DIR), *roots]),
               REDFIRST_REPORT_PATH=str(out / "report.json"), PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-p", "collector_plugin",
         "-p", "no:cacheprovider", "--rootdir", str(gen), "-q", "--tb=short"],
        cwd=repo_root, env=env, capture_output=True, encoding="utf-8", errors="replace",
        timeout=120, check=False,
    )
    report, problem = read_report(out / "report.json")
    result = build_run_result(report, report_problem=problem, exit_code=proc.returncode,
                              repo_root=str(repo_root), test_file=str(test_file.resolve()))
    return SandboxRun(result, proc.returncode, int((time.monotonic() - started) * 1000),
                      proc.stdout, proc.stderr, False)


def zip_fixture(name: str, dest: Path) -> Path:
    src = FIXTURE_REPOS / name
    archive = dest / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                zf.write(p, f"{name}/{p.relative_to(src).as_posix()}")
    return archive


@pytest.fixture
def fixture_zip(tmp_path):
    return lambda name: zip_fixture(name, tmp_path)
