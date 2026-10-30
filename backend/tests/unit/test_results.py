"""D1 + D3: building a RunResult from an untrusted collector report and trusted runner facts."""

import copy
import json
import os

import pytest

from redfirst.domain.enums import Outcome as O
from redfirst.domain.enums import OutcomeReason as R
from redfirst.domain.enums import TestStatus as T
from redfirst.sandbox.results import MAX_REPORT_BYTES, build_run_result, read_report
from redfirst.verification.models import FailureSignature, TestContract
from redfirst.verification.rules import classify

DOCKER = {"repo_root": "/repo", "test_file": "/gen/test_redfirst.py"}

CONTRACT = TestContract(target_modules=["app/users.py"],
                        expected_signature=FailureSignature(exception_type="KeyError"),
                        has_control_test=True, exercises_target=True)


def phases(call: dict | None = None, setup="passed") -> dict:
    p = {"setup": {"outcome": setup}, "teardown": {"outcome": "passed"}}
    if call is not None:
        p["call"] = call
    return {"phases": p}


def report(main_call: dict, exitstatus: int, control="passed") -> dict:
    return {
        "exitstatus": exitstatus,
        "collection_errors": [],
        "tests": {
            "test_redfirst.py::test_control": phases({"outcome": control}),
            "test_redfirst.py::test_reproduces_bug": phases(main_call),
        },
    }


FAILED_CALL = {
    "outcome": "failed", "exception_type": "KeyError", "message": "'username'",
    "frames": [{"file": "/gen/test_redfirst.py", "function": "test_reproduces_bug"},
               {"file": "/repo/app/users.py", "function": "register"}],
}
FAILING = report(FAILED_CALL, exitstatus=1)
PASSING = report({"outcome": "passed"}, exitstatus=0)


def verdict(rep, exit_code, **kw):
    return classify([build_run_result(rep, exit_code=exit_code, **{**DOCKER, **kw})], CONTRACT)


# --- ordinary, consistent results are unchanged ---------------------------------------------
def test_consistent_failing_report_reproduces_with_canonical_frames():
    r = build_run_result(FAILING, exit_code=1, **DOCKER)
    assert r.integrity_errors == [] and r.exit_code == 1
    assert [f.in_generated_test for f in r.frames] == [True, False]
    assert [f.repo_path for f in r.frames] == [None, "app/users.py"]
    v = classify([r], CONTRACT)
    assert (v.outcome, v.reason) == (O.REPRODUCED, R.MATCHING_FAILURE)


def test_consistent_passing_report_is_not_reproduced():
    v = verdict(PASSING, 0)
    assert (v.outcome, v.reason) == (O.NOT_REPRODUCED, R.NO_FAILURE_OBSERVED)


def test_windows_host_paths_are_mapped_into_the_repository():
    rep = copy.deepcopy(FAILING)
    call = rep["tests"]["test_redfirst.py::test_reproduces_bug"]["phases"]["call"]
    call["frames"] = [{"file": "C:\\w\\gen\\test_redfirst.py", "function": "test_reproduces_bug"},
                      {"file": "C:\\w\\repo\\app\\users.py", "function": "register"}]
    r = build_run_result(rep, exit_code=1, repo_root="c:/w/repo",
                         test_file="C:\\w\\gen\\test_redfirst.py")
    assert [f.repo_path for f in r.frames] == [None, "app/users.py"]
    assert r.frames[0].in_generated_test


def test_without_a_repo_root_no_frame_counts_as_target_code():
    r = build_run_result(FAILING, exit_code=1)
    assert all(f.repo_path is None for f in r.frames)
    assert classify([r], CONTRACT).outcome is O.INCONCLUSIVE


def test_collection_error_with_exit_code_2_is_setup_failure():
    rep = {"exitstatus": 2, "tests": {},
           "collection_errors": [{"nodeid": "test_redfirst.py", "message": "ImportError: x"}]}
    v = verdict(rep, 2)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.SETUP_FAILURE)


# --- D3: contradictions between the report and what the runner observed ----------------------
@pytest.mark.parametrize(("rep", "exit_code", "fragment"), [
    (FAILING, 0, "implies exit code 1"),      # report shows a failure, process exited 0
    (PASSING, 1, "implies exit code 0"),      # report shows success, process exited 1
    (report(FAILED_CALL, exitstatus=0), 1, "says pytest exited with 0"),
    ({"exitstatus": 1, "tests": {},
      "collection_errors": [{"nodeid": "test_redfirst.py", "message": "x"}]}, 1,
     "implies exit code 2"),
    ({"exitstatus": 0, "tests": {}, "collection_errors": []}, 0, "implies exit code 5"),
])
def test_report_contradicting_the_exit_code_is_invalid(rep, exit_code, fragment):
    r = build_run_result(rep, exit_code=exit_code, **DOCKER)
    assert any(fragment in e for e in r.integrity_errors), r.integrity_errors
    assert r.main_status is T.MISSING  # an untrusted report never fills in test outcomes
    v = classify([r], CONTRACT)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.INVALID_REPORT)


@pytest.mark.parametrize(("mutate", "fragment"), [
    (lambda r: r.update(extra_field=1), "malformed"),
    (lambda r: r.update(exitstatus="1"), "malformed"),
    (lambda r: r["tests"].update({"other_file.py::test_reproduces_bug": phases(
        {"outcome": "passed"})}), "not from the generated test file"),
    (lambda r: r["tests"]["test_redfirst.py::test_reproduces_bug"]["phases"].pop("setup"),
     "has no setup phase"),
    (lambda r: r["tests"]["test_redfirst.py::test_control"]["phases"]["setup"].update(
        outcome="failed"), "ran its call phase after setup"),
    (lambda r: r["tests"]["test_redfirst.py::test_reproduces_bug"]["phases"]["call"].update(
        outcome="exploded"), "malformed"),
    (lambda r: r["tests"].update({f"test_redfirst.py::test_{i}": phases({"outcome": "passed"})
                                  for i in range(600)}), "malformed"),  # schema allows 500
])
def test_malformed_or_impossible_reports_are_invalid(mutate, fragment):
    rep = copy.deepcopy(FAILING)
    mutate(rep)
    r = build_run_result(rep, exit_code=1, **DOCKER)
    assert any(fragment in e for e in r.integrity_errors), r.integrity_errors
    v = classify([r], CONTRACT)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.INVALID_REPORT)


@pytest.mark.parametrize("data", [None, [], "text", 7, {"tests": "nope"}])
def test_non_object_or_missing_reports_are_invalid(data):
    r = build_run_result(data, exit_code=1, **DOCKER)
    assert r.integrity_errors and r.main_status is T.MISSING
    assert classify([r], CONTRACT).reason is R.INVALID_REPORT


def test_report_problem_from_reading_is_kept_as_evidence():
    r = build_run_result(None, report_problem="report is not valid JSON", exit_code=1, **DOCKER)
    v = classify([r], CONTRACT)
    assert v.reason is R.INVALID_REPORT and any("not valid JSON" in e for e in v.evidence)


def test_malformed_report_errors_do_not_echo_report_values():
    rep = copy.deepcopy(FAILING)
    rep["exitstatus"] = "SECRET-VALUE-sk-ant-api03-abcdefghijklmnop"
    r = build_run_result(rep, exit_code=1, **DOCKER)
    assert r.integrity_errors and "SECRET-VALUE" not in " ".join(r.integrity_errors)


def test_unknown_exit_code_is_a_runner_failure():
    r = build_run_result(FAILING, **DOCKER)
    assert r.runner_crashed
    assert classify([r], CONTRACT).outcome is O.EXECUTION_ERROR


def test_pytest_internal_error_without_report_is_a_runner_failure():
    r = build_run_result(None, exit_code=3, **DOCKER)
    assert classify([r], CONTRACT).outcome is O.EXECUTION_ERROR


def test_killed_runs_ignore_the_report_entirely():
    r = build_run_result(PASSING, exit_code=137, oom_killed=True, **DOCKER)
    assert r.main_status is T.MISSING
    assert classify([r], CONTRACT).reason is R.RESOURCE_LIMIT


# --- reading the report file as untrusted input ---------------------------------------------
def test_read_report_valid(tmp_path):
    p = tmp_path / "report.json"
    p.write_text(json.dumps(PASSING))
    assert read_report(p) == (PASSING, None)


def test_read_report_missing(tmp_path):
    data, problem = read_report(tmp_path / "report.json")
    assert data is None and "no structured report" in problem


def test_read_report_invalid_json(tmp_path):
    p = tmp_path / "report.json"
    p.write_bytes(b"{not json")
    data, problem = read_report(p)
    assert data is None and "not valid JSON" in problem


def test_read_report_too_large(tmp_path):
    p = tmp_path / "report.json"
    p.write_bytes(b" " * (MAX_REPORT_BYTES + 1))
    data, problem = read_report(p)
    assert data is None and "larger than" in problem


def test_read_report_refuses_symlinks(tmp_path):
    # Code in the sandbox can create a symlink in the output directory pointing at a host
    # file; the trusted runner must not follow it.
    secret = tmp_path / "host-secret.json"
    secret.write_text(json.dumps(PASSING))
    link = tmp_path / "report.json"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform/user cannot create symlinks")
    data, problem = read_report(link)
    assert data is None and "symlink" in problem
