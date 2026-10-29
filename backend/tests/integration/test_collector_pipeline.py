"""collector plugin -> RunResult -> verifier, using a plain local pytest subprocess.

This exercises parsing only. It is NOT sandboxed and only runs our own fixture code.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from redfirst.domain.enums import Outcome as O
from redfirst.domain.enums import OutcomeReason as R
from redfirst.sandbox import collector_plugin
from redfirst.sandbox.results import build_run_result
from redfirst.verification.models import FailureSignature, TestContract
from redfirst.verification.rules import classify

PLUGIN_DIR = Path(collector_plugin.__file__).parent

REPO = {
    "app/__init__.py": "",
    "app/users.py": 'def register(data):\n    return data["username"]\n',
    "app/other.py": "def boom():\n    raise ValueError('unrelated')\n",
}

CONTRACT = TestContract(
    target_modules=["app/users.py"],
    expected_signature=FailureSignature(exception_type="KeyError"),
    has_control_test=True,
    exercises_target=True,
)


def run_local(tmp_path: Path, test_code: str) -> dict | None:
    repo = tmp_path / "repo"
    for name, text in REPO.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "test_redfirst.py").write_text(test_code)
    report = tmp_path / "report.json"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(PLUGIN_DIR), str(repo)]),
           "REDFIRST_REPORT_PATH": str(report), "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run(
        [sys.executable, "-m", "pytest", str(gen / "test_redfirst.py"), "-p",
         "collector_plugin", "-p", "no:cacheprovider", "--rootdir", str(gen), "-q"],
        env=env, cwd=repo, capture_output=True, timeout=60, check=False,
    )
    return json.loads(report.read_text()) if report.is_file() else None


def verdict(tmp_path, code, runs=2):
    result = build_run_result(run_local(tmp_path, code))
    return classify([result] * runs, CONTRACT)


CONTROL = 'def test_control():\n    assert register({"username": "a"}) == "a"\n'
IMPORT = "from app.users import register\n"


def test_real_keyerror_bug_is_reproduced(tmp_path):
    code = IMPORT + CONTROL + (
        'def test_reproduces_bug():\n    assert register({"email": "x@y.z"}) is not None\n'
    )
    v = verdict(tmp_path, code)
    assert (v.outcome, v.reason) == (O.REPRODUCED, R.MATCHING_FAILURE), v


def test_passing_test_is_not_reproduced(tmp_path):
    code = IMPORT + CONTROL + (
        'def test_reproduces_bug():\n    assert register({"username": "b"}) == "b"\n'
    )
    v = verdict(tmp_path, code)
    assert (v.outcome, v.reason) == (O.NOT_REPRODUCED, R.NO_FAILURE_OBSERVED), v


def test_import_error_is_setup_failure_not_reproduction(tmp_path):
    code = "from app.missing import register\n" + CONTROL + (
        "def test_reproduces_bug():\n    register({})\n"
    )
    v = verdict(tmp_path, code)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.SETUP_FAILURE), v


def test_fixture_error_is_setup_failure(tmp_path):
    code = IMPORT + CONTROL + (
        "import pytest\n@pytest.fixture\ndef db():\n    raise RuntimeError('no database')\n"
        "def test_reproduces_bug(db):\n    register({})\n"
    )
    v = verdict(tmp_path, code)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.SETUP_FAILURE), v


def test_failure_in_unrelated_module_is_not_reproduction(tmp_path):
    code = IMPORT + "from app.other import boom\n" + CONTROL + (
        "def test_reproduces_bug():\n    boom()\n"
    )
    v = verdict(tmp_path, code)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.UNRELATED_FAILURE), v


def test_wrong_assertion_is_not_matching_signature(tmp_path):
    code = IMPORT + CONTROL + (
        'def test_reproduces_bug():\n    assert register({"username": "a"}) == "zzz"\n'
    )
    v = verdict(tmp_path, code)
    # AssertionError raised inside the test file, not in target code
    assert v.outcome is O.INCONCLUSIVE, v


def test_missing_report_is_not_parsed():
    result = build_run_result(None)
    assert classify([result], CONTRACT).outcome is O.EXECUTION_ERROR


def test_timeout_is_resource_limit():
    result = build_run_result(None, timed_out=True)
    v = classify([result], CONTRACT)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.RESOURCE_LIMIT)


def test_missing_main_test_is_inconclusive(tmp_path):
    code = IMPORT + CONTROL + "def test_something_else():\n    pass\n"
    v = verdict(tmp_path, code)
    assert v.outcome is O.INCONCLUSIVE, v


@pytest.mark.parametrize("flag", ["runner_crashed"])
def test_runner_crash_is_execution_error(flag):
    v = classify([build_run_result(None, **{flag: True})], CONTRACT)
    assert v.outcome is O.EXECUTION_ERROR
