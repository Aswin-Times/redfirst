"""Shared test helpers.

``local_executor`` runs a generated test with plain pytest in a subprocess. It is NOT a
sandbox and must only ever run the project's own fixture repositories.
"""

import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from redfirst.sandbox.executor import PLUGIN_DIR, ExecRequest
from redfirst.sandbox.results import build_run_result
from redfirst.sandbox.runner import SandboxRun

FIXTURE_REPOS = Path(__file__).resolve().parents[2] / "fixtures" / "repos"


def local_executor(request: ExecRequest) -> SandboxRun:
    gen, out = request.work_dir / "gen", request.work_dir / "out"
    gen.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    (gen / "test_redfirst.py").write_text(request.test_code, encoding="utf-8")
    roots = [str((request.repo_dir / r).resolve()) for r in request.source_roots]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(PLUGIN_DIR), *roots]),
           "REDFIRST_REPORT_PATH": str(out / "report.json"), "PYTHONDONTWRITEBYTECODE": "1"}
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(gen / "test_redfirst.py"), "-p", "collector_plugin",
         "-p", "no:cacheprovider", "--rootdir", str(gen), "-q", "--tb=short"],
        cwd=request.repo_dir, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    report_path = out / "report.json"
    report = json.loads(report_path.read_text()) if report_path.is_file() else None
    return SandboxRun(build_run_result(report), proc.returncode,
                      int((time.monotonic() - started) * 1000), proc.stdout, proc.stderr, False)


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
