"""Real-Docker sandbox tests (marker: ``docker``).

These are the only tests that exercise the actual container sandbox. They are skipped when no
Docker daemon or sandbox image is available, unless REDFIRST_REQUIRE_DOCKER=1 is set (as in
.github/workflows/sandbox.yml), in which case unavailability is a failure, not a skip.

Build the image first:  docker build -t redfirst-sandbox-python:3.12 sandbox-images/python
Run:                    REDFIRST_REQUIRE_DOCKER=1 python -m pytest -m docker -rA

A passing run shows these specific abuses are contained by this configuration; it does not
prove the container cannot be escaped.
"""

import os
import subprocess

import pytest

from redfirst.domain.enums import Outcome, OutcomeReason, TestStatus
from redfirst.sandbox.executor import PLUGIN_DIR
from redfirst.sandbox.runner import docker_available, run_test_in_sandbox
from redfirst.verification.models import FailureSignature, TestContract
from redfirst.verification.rules import classify

IMAGE = "redfirst-sandbox-python:3.12"
REQUIRED = os.environ.get("REDFIRST_REQUIRE_DOCKER") == "1"


def _image_present() -> bool:
    if not docker_available():
        return False
    proc = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    return proc.returncode == 0


AVAILABLE = _image_present()
pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not AVAILABLE and not REQUIRED,
                       reason="docker or sandbox image unavailable (set REDFIRST_REQUIRE_DOCKER=1 "
                              "to make this a failure)"),
]


@pytest.fixture(autouse=True)
def _require_docker():
    if not AVAILABLE:
        pytest.fail(f"REDFIRST_REQUIRE_DOCKER=1 but docker or image {IMAGE} is unavailable",
                    pytrace=False)


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


def container_gone(name: str) -> bool:
    proc = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^/{name}$",
                           "--format", "{{.Names}}"], capture_output=True, text=True, check=False)
    return proc.returncode == 0 and proc.stdout.strip() == ""


CONTRACT = TestContract(target_modules=["app/users.py"],
                        expected_signature=FailureSignature(exception_type="KeyError"),
                        exercises_target=True)


def test_failing_test_reproduces_with_repository_frames(repo, tmp_path):
    code = ("from app.users import register\n"
            "def test_reproduces_bug():\n    register({})\n")
    out = run(repo, tmp_path, code)
    r = out.result
    assert out.exit_code == 1 and r.integrity_errors == [], (r, out.stderr[-2000:])
    assert r.main_status is TestStatus.FAILED and r.exception_type == "KeyError"
    assert [f.repo_path for f in r.frames if f.repo_path] == ["app/users.py"]
    assert r.frames[0].in_generated_test
    v = classify([r], CONTRACT)
    assert (v.outcome, v.reason) == (Outcome.REPRODUCED, OutcomeReason.MATCHING_FAILURE)
    assert out.container_removed and container_gone(out.container_name)


def test_passing_test_is_not_reproduced_and_cleans_up(repo, tmp_path):
    code = ("from app.users import register\n"
            "def test_reproduces_bug():\n    assert register({'username': 'a'}) == 'a'\n")
    out = run(repo, tmp_path, code)
    assert out.exit_code == 0 and out.result.integrity_errors == [], out.stderr[-2000:]
    assert classify([out.result], CONTRACT).outcome is Outcome.NOT_REPRODUCED
    assert out.container_removed and container_gone(out.container_name)


def test_infinite_loop_times_out_and_the_container_is_removed(repo, tmp_path):
    out = run(repo, tmp_path, "def test_reproduces_bug():\n    while True:\n        pass\n",
              timeout_seconds=5)
    assert out.result.timed_out
    assert classify([out.result], CONTRACT).reason is OutcomeReason.RESOURCE_LIMIT
    assert out.container_removed and container_gone(out.container_name)


def test_memory_exhaustion_is_reported_as_an_oom_kill(repo, tmp_path):
    code = ("def test_reproduces_bug():\n"
            "    chunks = []\n"
            "    while True:\n"
            "        chunks.append(b'x' * (64 * 1024 * 1024))\n")
    out = run(repo, tmp_path, code, memory="256m")
    assert out.result.oom_killed, (out.exit_code, out.stderr[-2000:])
    assert classify([out.result], CONTRACT).reason is OutcomeReason.RESOURCE_LIMIT
    assert out.container_removed and container_gone(out.container_name)


def test_network_is_blocked(repo, tmp_path):
    code = ("import socket\n"
            "def test_reproduces_bug():\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n")
    out = run(repo, tmp_path, code)
    assert out.result.main_status is TestStatus.FAILED
    assert out.result.exception_type in {"OSError", "TimeoutError", "ConnectionRefusedError",
                                         "gaierror"}, out.result


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
    assert out.result.timed_out or out.exit_code is not None
    assert out.container_removed and container_gone(out.container_name)


def test_huge_output_is_truncated(repo, tmp_path):
    # pytest prints the captured output of a *failing* test, so this produces ~5 MB of stdout.
    code = "def test_reproduces_bug():\n    print('x' * 5_000_000)\n    assert False\n"
    out = run(repo, tmp_path, code)
    assert out.output_truncated and len(out.stdout) <= 256 * 1024


def test_report_rewritten_by_repository_code_is_rejected(repo, tmp_path):
    (repo / "app" / "users.py").write_text(
        "import atexit, json, os\n"
        "def _forge():\n"
        "    ok = {'setup': {'outcome': 'passed'}, 'call': {'outcome': 'passed'},\n"
        "          'teardown': {'outcome': 'passed'}}\n"
        "    with open(os.environ['REDFIRST_REPORT_PATH'], 'w') as fh:\n"
        "        json.dump({'exitstatus': 0, 'collection_errors': [], 'tests': {\n"
        "            'test_redfirst.py::test_reproduces_bug': {'phases': ok}}}, fh)\n"
        "atexit.register(_forge)\n"
        "def register(d):\n    return d['username']\n")
    code = ("from app.users import register\n"
            "def test_reproduces_bug():\n    register({})\n")
    out = run(repo, tmp_path, code)
    assert out.exit_code == 1
    v = classify([out.result], CONTRACT)
    assert (v.outcome, v.reason) == (Outcome.INCONCLUSIVE, OutcomeReason.INVALID_REPORT)
