"""D3: the structured report is written inside the test process, so code under test can rewrite
it. These tests run plain local pytest (NOT the Docker sandbox) on repository code written here
to tamper with the report, and check that REDFIRST fails closed instead of trusting it.
"""

from pathlib import Path

import pytest

from redfirst.domain.enums import Outcome as O
from redfirst.domain.enums import OutcomeReason as R
from redfirst.sandbox.executor import ExecRequest
from redfirst.verification.models import FailureSignature, TestContract
from redfirst.verification.rules import classify
from tests.conftest import local_executor

CONTRACT = TestContract(target_modules=["app/users.py"],
                        expected_signature=FailureSignature(exception_type="KeyError"),
                        has_control_test=True, exercises_target=True)

TEST_CODE = (
    "from app.users import register\n\n"
    "def test_control():\n    assert register({'username': 'a'}) == 'a'\n\n"
    "def test_reproduces_bug():\n    register({'email': 'x'})\n"  # genuinely raises KeyError
)

REGISTER = "def register(d):\n    return d['username']\n"

# A "repository" module that, after pytest has written the real report, overwrites it with one
# claiming both tests passed. {exit} is the exit status the forged report claims; {tail} runs last.
FORGER = """
import atexit, json, os

def _forge():
    ok = {{"setup": {{"outcome": "passed"}}, "call": {{"outcome": "passed"}},
           "teardown": {{"outcome": "passed"}}}}
    with open(os.environ["REDFIRST_REPORT_PATH"], "w") as fh:
        json.dump({{"exitstatus": {exit}, "collection_errors": [], "tests": {{
            "test_redfirst.py::test_reproduces_bug": {{"phases": ok}},
            "test_redfirst.py::test_control": {{"phases": ok}}}}}}, fh)
    {tail}

atexit.register(_forge)
"""


def run_repo(tmp_path: Path, users_py: str):
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "__init__.py").write_text("")
    (repo / "app" / "users.py").write_text(users_py)
    return local_executor(ExecRequest(repo_dir=repo, test_code=TEST_CODE,
                                      work_dir=tmp_path / "work", source_roots=(".",)))


def test_untampered_run_reproduces(tmp_path):
    run = run_repo(tmp_path, REGISTER)
    assert run.exit_code == 1 and run.result.integrity_errors == []
    v = classify([run.result], CONTRACT)
    assert (v.outcome, v.reason) == (O.REPRODUCED, R.MATCHING_FAILURE)


def test_report_rewritten_after_pytest_finished_is_rejected(tmp_path):
    run = run_repo(tmp_path, FORGER.format(exit=0, tail="pass") + REGISTER)
    assert run.exit_code == 1  # the real outcome: a test failed
    v = classify([run.result], CONTRACT)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.INVALID_REPORT), v
    assert any("exit code 1" in e for e in v.evidence)


def test_forged_report_keeping_the_real_exit_status_is_still_rejected(tmp_path):
    # The forger claims exitstatus 1 to match the process, but its "all passed" content
    # implies exit code 0.
    run = run_repo(tmp_path, FORGER.format(exit=1, tail="pass") + REGISTER)
    v = classify([run.result], CONTRACT)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.INVALID_REPORT), v


@pytest.mark.xfail(strict=True, reason=(
    "Known limitation (docs/threat-model.md): code running inside the test process that "
    "controls both the report and its own exit status can forge a consistent result. "
    "No in-process signal can detect this; the sandbox only limits what such code can reach."))
def test_forgery_that_also_controls_the_exit_status_is_detected(tmp_path):
    run = run_repo(tmp_path, FORGER.format(exit=0, tail="os._exit(0)") + REGISTER)
    v = classify([run.result], CONTRACT)
    assert v.outcome is not O.NOT_REPRODUCED
