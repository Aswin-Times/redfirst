"""Real-Docker sandbox tests. Skipped unless a Docker daemon and the sandbox image exist.

Build the image first:  docker build -t redfirst-sandbox-python:3.12 sandbox-images/python
"""

import subprocess
from pathlib import Path

import pytest

from redfirst.domain.enums import TestStatus
from redfirst.sandbox import collector_plugin
from redfirst.sandbox.runner import docker_available, run_test_in_sandbox

IMAGE = "redfirst-sandbox-python:3.12"
PLUGIN_DIR = Path(collector_plugin.__file__).parent


def _image_present() -> bool:
    if not docker_available():
        return False
    proc = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    return proc.returncode == 0


pytestmark = pytest.mark.skipif(not _image_present(), reason="docker or sandbox image unavailable")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "app").mkdir(parents=True)
    (r / "app" / "__init__.py").write_text("")
    (r / "app" / "users.py").write_text('def register(d):\n    return d["username"]\n')
    return r


def run(repo, tmp_path, code, **kw):
    return run_test_in_sandbox(image=IMAGE, repo_dir=repo, test_code=code, plugin_dir=PLUGIN_DIR,
                               work_dir=tmp_path / "work", **kw)


def test_basic_run_reports_failure(repo, tmp_path):
    code = ("from app.users import register\n"
            "def test_reproduces_bug():\n    register({})\n")
    out = run(repo, tmp_path, code)
    assert out.result.main_status is TestStatus.FAILED
    assert out.result.exception_type == "KeyError"


def test_infinite_loop_times_out(repo, tmp_path):
    out = run(repo, tmp_path, "def test_reproduces_bug():\n    while True:\n        pass\n",
              timeout_seconds=5)
    assert out.result.timed_out


def test_network_is_blocked(repo, tmp_path):
    code = ("import socket\n"
            "def test_reproduces_bug():\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n")
    out = run(repo, tmp_path, code)
    assert out.result.main_status is TestStatus.FAILED


def test_repo_is_read_only(repo, tmp_path):
    code = "def test_reproduces_bug():\n    open('/repo/x.txt', 'w').write('x')\n"
    out = run(repo, tmp_path, code)
    assert out.result.main_status is TestStatus.FAILED
    assert not (repo / "x.txt").exists()


def test_fork_bomb_is_contained(repo, tmp_path):
    code = ("import os\n"
            "def test_reproduces_bug():\n"
            "    for _ in range(100000):\n        os.fork()\n")
    out = run(repo, tmp_path, code, timeout_seconds=20)
    assert out.exit_code is not None or out.result.timed_out


def test_memory_blowup_is_killed(repo, tmp_path):
    code = "def test_reproduces_bug():\n    x = bytearray(2 * 1024**3)\n"
    out = run(repo, tmp_path, code, memory="256m")
    assert out.result.oom_killed or out.result.main_status is TestStatus.FAILED


def test_huge_output_is_truncated(repo, tmp_path):
    code = "def test_reproduces_bug():\n    print('x' * 5_000_000)\n"
    out = run(repo, tmp_path, code)
    assert len(out.stdout) <= 256 * 1024
