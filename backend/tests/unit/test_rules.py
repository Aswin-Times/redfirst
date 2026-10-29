from redfirst.domain.enums import Outcome as O
from redfirst.domain.enums import OutcomeReason as R
from redfirst.domain.enums import TestPhase as P
from redfirst.domain.enums import TestStatus as T
from redfirst.verification.models import (
    FailureSignature,
    RunResult,
    TestContract,
    TracebackFrame,
)
from redfirst.verification.rules import classify


def contract(**kw):
    base = dict(
        target_modules=["app/users.py"],
        expected_signature=FailureSignature(exception_type="KeyError"),
        has_control_test=True,
        exercises_target=True,
    )
    base.update(kw)
    return TestContract(**base)


def run(**kw):
    base = dict(
        main_status=T.FAILED,
        main_phase=P.CALL,
        control_status=T.PASSED,
        exception_type="KeyError",
        message="'username'",
        frames=[TracebackFrame(file="/repo/app/users.py", function="register")],
    )
    base.update(kw)
    return RunResult(**base)


def check(runs, c=None, outcome=None, reason=None):
    v = classify(runs, c or contract())
    assert (v.outcome, v.reason) == (outcome, reason), v
    return v


def test_reproduced():
    v = check([run()] * 3, outcome=O.REPRODUCED, reason=R.MATCHING_FAILURE)
    assert v.evidence


def test_runner_crash_is_execution_error():
    check([run(runner_crashed=True)], outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE)


def test_unparseable_report_is_execution_error():
    check([run(report_parsed=False)], outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE)


def test_import_error_in_collection_is_not_reproduction():
    check([run(collection_error=True, main_phase=P.COLLECTION)],
          outcome=O.INCONCLUSIVE, reason=R.SETUP_FAILURE)


def test_fixture_error_in_setup_is_not_reproduction():
    check([run(main_status=T.ERROR, main_phase=P.SETUP)],
          outcome=O.INCONCLUSIVE, reason=R.SETUP_FAILURE)


def test_timeout_and_oom_are_resource_limit():
    check([run(timed_out=True)], outcome=O.INCONCLUSIVE, reason=R.RESOURCE_LIMIT)
    check([run(oom_killed=True)], outcome=O.INCONCLUSIVE, reason=R.RESOURCE_LIMIT)


def test_failed_control_blocks_conclusions():
    check([run(control_status=T.FAILED)], outcome=O.INCONCLUSIVE, reason=R.CONTROL_FAILED)


def test_missing_expected_behavior_caps_at_inconclusive():
    check([run()], contract(expected_behavior_known=False),
          outcome=O.INCONCLUSIVE, reason=R.NO_EXPECTED_BEHAVIOR)


def test_passing_test_is_not_reproduced():
    check([run(main_status=T.PASSED, exception_type=None, frames=[])],
          outcome=O.NOT_REPRODUCED, reason=R.NO_FAILURE_OBSERVED)


def test_passing_test_that_never_hits_target_is_inconclusive():
    check([run(main_status=T.PASSED, exception_type=None, frames=[])],
          contract(exercises_target=False),
          outcome=O.INCONCLUSIVE, reason=R.TARGET_NOT_EXERCISED)


def test_failure_outside_target_is_unrelated():
    r = run(frames=[TracebackFrame(file="/repo/app/other.py", function="f")])
    check([r], outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_wrong_exception_type_is_signature_mismatch():
    check([run(exception_type="ValueError")],
          outcome=O.INCONCLUSIVE, reason=R.SIGNATURE_MISMATCH)


def test_message_substring_must_match():
    c = contract(expected_signature=FailureSignature(message_contains="boom"))
    check([run(message="other")], c, outcome=O.INCONCLUSIVE, reason=R.SIGNATURE_MISMATCH)
    check([run(message="boom!")], c, outcome=O.REPRODUCED, reason=R.MATCHING_FAILURE)


def test_empty_signature_never_reproduces():
    c = contract(expected_signature=FailureSignature())
    check([run()], c, outcome=O.INCONCLUSIVE, reason=R.SIGNATURE_MISMATCH)


def test_flaky_runs_are_not_repeatable():
    check([run(), run(main_status=T.PASSED, exception_type=None, frames=[]), run()],
          outcome=O.INCONCLUSIVE, reason=R.NOT_REPEATABLE)


def test_runner_error_in_any_run_dominates():
    check([run(), run(runner_crashed=True), run()],
          outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE)


def test_no_runs_is_execution_error():
    check([], outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE)
