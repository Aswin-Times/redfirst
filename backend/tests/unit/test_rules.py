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
        exit_code=1,
        frames=[TracebackFrame(file="/repo/app/users.py", function="register",
                               repo_path="app/users.py")],
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


def test_missing_or_unusable_report_is_invalid_not_a_verdict():
    # Changed in M9 (D3): the report is produced inside the sandbox, where the code under test
    # can delete or corrupt it, so a missing report after a normal exit is an untrusted result,
    # not proof of an infrastructure failure. It must never become REPRODUCED/NOT_REPRODUCED.
    v = check([run(report_parsed=False, integrity_errors=["no structured report was produced"])],
              outcome=O.INCONCLUSIVE, reason=R.INVALID_REPORT)
    assert any("no structured report" in e for e in v.evidence)


def test_missing_report_with_pytest_internal_error_is_execution_error():
    for code in (3, 4):  # pytest internal error / usage error: a runner or collector problem
        check([run(report_parsed=False, exit_code=code)],
              outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE)


def test_integrity_errors_override_an_otherwise_reproduced_run():
    v = check([run(integrity_errors=["pytest exited with 0, but the report implies 1"])],
              outcome=O.INCONCLUSIVE, reason=R.INVALID_REPORT)
    assert any("exited with 0" in e for e in v.evidence)


def test_integrity_errors_override_an_otherwise_not_reproduced_run():
    passed = run(main_status=T.PASSED, exception_type=None, frames=[], exit_code=0,
                 integrity_errors=["report contradicts exit code"])
    check([passed], outcome=O.INCONCLUSIVE, reason=R.INVALID_REPORT)


def test_import_error_in_collection_is_not_reproduction():
    check([run(collection_error=True, main_phase=P.COLLECTION)],
          outcome=O.INCONCLUSIVE, reason=R.SETUP_FAILURE)


def test_fixture_error_in_setup_is_not_reproduction():
    check([run(main_status=T.ERROR, main_phase=P.SETUP)],
          outcome=O.INCONCLUSIVE, reason=R.SETUP_FAILURE)


def test_timeout_and_oom_are_resource_limit():
    check([run(timed_out=True)], outcome=O.INCONCLUSIVE, reason=R.RESOURCE_LIMIT)
    check([run(oom_killed=True)], outcome=O.INCONCLUSIVE, reason=R.RESOURCE_LIMIT)


def test_killed_run_without_report_is_resource_limit_not_runner_error():
    check([run(timed_out=True, report_parsed=False)], outcome=O.INCONCLUSIVE,
          reason=R.RESOURCE_LIMIT)
    check([run(oom_killed=True, report_parsed=False)], outcome=O.INCONCLUSIVE,
          reason=R.RESOURCE_LIMIT)


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


def _assert_run(function="test_reproduces_bug"):
    return run(exception_type="AssertionError", message="assert 0.0 == 0.1",
               frames=[TracebackFrame(file="/gen/test_redfirst.py", function=function,
                                      in_generated_test=True)])


def test_wrong_value_assertion_in_main_test_is_reproduced():
    c = contract(expected_signature=FailureSignature(exception_type="AssertionError"),
                 asserts_on_target_result=True)
    v = check([_assert_run()] * 3, c, outcome=O.REPRODUCED, reason=R.MATCHING_FAILURE)
    assert any("assertion on target" in e for e in v.evidence)


def test_wrong_value_allowance_requires_target_exercised():
    c = contract(expected_signature=FailureSignature(exception_type="AssertionError"),
                 exercises_target=False)
    check([_assert_run()], c, outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_wrong_value_allowance_requires_predicted_assertion():
    check([_assert_run()], outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_assertion_in_helper_not_main_test_is_unrelated():
    c = contract(expected_signature=FailureSignature(exception_type="AssertionError"),
                 asserts_on_target_result=True)
    check([_assert_run(function="helper")], c, outcome=O.INCONCLUSIVE,
          reason=R.UNRELATED_FAILURE)


# --- D1: target matching is repository-relative, never a bare filename suffix -------------
def test_library_file_whose_name_ends_with_the_target_is_not_target_code():
    c = contract(target_modules=["utils.py"])
    r = run(frames=[
        TracebackFrame(file="/gen/test_redfirst.py", function="test_reproduces_bug",
                       in_generated_test=True),
        TracebackFrame(file="/usr/local/lib/python3.12/site-packages/lib/myutils.py",
                       function="helper"),
    ])
    check([r] * 3, c, outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_installed_copy_with_the_same_relative_path_is_not_target_code():
    r = run(frames=[TracebackFrame(
        file="/usr/local/lib/python3.12/site-packages/app/users.py", function="register")])
    check([r], outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_sibling_directory_sharing_a_prefix_is_not_target_code():
    # "/repository/..." must not be treated as inside "/repo"; the runner leaves repo_path
    # unset for it, so even a matching tail is not evidence.
    r = run(frames=[TracebackFrame(file="/repository/app/users.py", function="register")])
    check([r], outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_non_canonical_target_spellings_still_match_the_repository_path():
    for target in ("app\\users.py", "./app/users.py", "app//users.py"):
        check([run()], contract(target_modules=[target]),
              outcome=O.REPRODUCED, reason=R.MATCHING_FAILURE)


def test_unsafe_target_spellings_never_match():
    for target in ("/repo/app/users.py", "../app/users.py", "C:/repo/app/users.py"):
        check([run()], contract(target_modules=[target]),
              outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_reproduced_evidence_names_the_matching_target_frame():
    v = check([run()], outcome=O.REPRODUCED, reason=R.MATCHING_FAILURE)
    assert any("app/users.py:register" in e for e in v.evidence)


def test_wrong_value_allowance_requires_the_generated_test_file():
    # A repository function that happens to be called test_reproduces_bug is not the test.
    c = contract(expected_signature=FailureSignature(exception_type="AssertionError"),
                 asserts_on_target_result=True)
    r = run(exception_type="AssertionError", message="assert 1 == 2", frames=[TracebackFrame(
        file="/repo/app/helpers.py", function="test_reproduces_bug", repo_path="app/helpers.py")])
    check([r], c, outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_main_test_name_matches_sandbox_constant():
    from redfirst.sandbox.results import MAIN_TEST
    from redfirst.verification.rules import MAIN_TEST_NAME
    assert MAIN_TEST == MAIN_TEST_NAME


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


# --- M9.1 R1: the wrong-value allowance needs a validator-established target-dependent assert --
def test_wrong_value_allowance_requires_assertion_on_target_result():
    c = contract(expected_signature=FailureSignature(exception_type="AssertionError"),
                 asserts_on_target_result=False)
    check([_assert_run()] * 3, c, outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE)


def test_wrong_value_allowance_with_target_dependent_assertion_still_reproduces():
    c = contract(expected_signature=FailureSignature(exception_type="AssertionError"),
                 asserts_on_target_result=True)
    check([_assert_run()] * 3, c, outcome=O.REPRODUCED, reason=R.MATCHING_FAILURE)
