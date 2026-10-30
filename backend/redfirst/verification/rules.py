"""Deterministic outcome classification. No LLM involvement.

Rules are evaluated in order; the first match decides.
"""

from redfirst.domain.enums import Outcome as O
from redfirst.domain.enums import OutcomeReason as R
from redfirst.domain.enums import TestPhase, TestStatus
from redfirst.verification.models import RunResult, TestContract, TracebackFrame, Verdict
from redfirst.verification.paths import canonical_target

MAIN_TEST_NAME = "test_reproduces_bug"  # must match sandbox.results.MAIN_TEST
PYTEST_INTERNAL_ERRORS = (3, 4)  # must match sandbox.results.PYTEST_INTERNAL_ERRORS


def _signature_matches(run: RunResult, contract: TestContract) -> bool:
    sig = contract.expected_signature
    if sig.exception_type is None and sig.message_contains is None:
        return False  # an empty signature can never confirm a defect
    if sig.exception_type and run.exception_type != sig.exception_type:
        return False
    return not (sig.message_contains and sig.message_contains not in run.message)


def _target_frames(run: RunResult, contract: TestContract) -> list[TracebackFrame]:
    """Frames whose repository-relative path equals a contract target exactly.

    ``repo_path`` is set by the runner only for files inside the repository root, so library
    files, installed copies and look-alike names elsewhere never match.
    """
    targets = {t for t in map(canonical_target, contract.target_modules) if t}
    return [f for f in run.frames if f.repo_path is not None and f.repo_path in targets]


def _wrong_value_in_main_test(run: RunResult, contract: TestContract) -> bool:
    """A wrong-return-value bug fails on the test's own assertion, not inside target code.

    Accepted only when an AssertionError was both predicted and observed, it was raised
    directly in the main test of the generated test file, the validator established that the
    test calls target code, and that every assertion in the main test depends on the result of
    target code (so `assert False` can never count as a reproduction).
    """
    last = run.frames[-1] if run.frames else None
    return (
        contract.expected_signature.exception_type == "AssertionError"
        and run.exception_type == "AssertionError"
        and contract.exercises_target
        and contract.asserts_on_target_result
        and last is not None
        and last.in_generated_test
        and last.function == MAIN_TEST_NAME
    )


def _classify_run(run: RunResult, contract: TestContract) -> Verdict:
    if run.runner_crashed:
        return Verdict(outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE,
                       evidence=[run.runner_error or "the runner could not run the test"])
    if run.timed_out or run.oom_killed or run.output_flooded:  # judged on the kill, not the report
        what = ("timeout" if run.timed_out else "out of memory" if run.oom_killed
                else "output limit exceeded (the run was stopped)")
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.RESOURCE_LIMIT, evidence=[what])
    if not run.report_parsed or run.integrity_errors:
        problems = run.integrity_errors or ["no usable structured report"]
        if run.exit_code in PYTEST_INTERNAL_ERRORS:
            return Verdict(outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE, evidence=[
                f"pytest exited with {run.exit_code} (internal or usage error)", *problems])
        # Fail closed: the report comes from inside the test process and cannot be trusted
        # here, so no conclusion is drawn about the bug.
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.INVALID_REPORT, evidence=[
            *problems, f"pytest exit code observed by the runner: {run.exit_code}"])
    if run.collection_error or run.main_phase in (TestPhase.COLLECTION, TestPhase.SETUP):
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.SETUP_FAILURE,
                       evidence=[f"failure before the test body ran: {run.message[:200]}"])
    if run.main_status is TestStatus.MISSING or run.main_status is TestStatus.SKIPPED:
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.UNCLASSIFIABLE,
                       evidence=[f"main test status: {run.main_status.value}"])
    if contract.has_control_test and run.control_status is not TestStatus.PASSED:
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.CONTROL_FAILED,
                       evidence=[f"control test status: {run.control_status}"])
    if not contract.expected_behavior_known:
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.NO_EXPECTED_BEHAVIOR,
                       evidence=["report gives no checkable expected behavior"])

    if run.main_status is TestStatus.PASSED:
        if not contract.exercises_target:
            return Verdict(outcome=O.INCONCLUSIVE, reason=R.TARGET_NOT_EXERCISED,
                           evidence=["test passed but was not shown to call target symbols"])
        return Verdict(outcome=O.NOT_REPRODUCED, reason=R.NO_FAILURE_OBSERVED,
                       evidence=["test passed under the tested conditions"])

    # FAILED or ERROR in the call/teardown phase
    if run.main_phase is not TestPhase.CALL:
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE,
                       evidence=[f"failure in phase {run.main_phase}"])
    in_target = _target_frames(run, contract)
    if not in_target and not _wrong_value_in_main_test(run, contract):
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE,
                       evidence=["no traceback frame in a target file inside the repository"])
    if not _signature_matches(run, contract):
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.SIGNATURE_MISMATCH,
                       evidence=[f"got {run.exception_type}: {run.message[:200]}"])
    if in_target:
        where = ["failure raised inside target code",
                 *[f"target frame {f.repo_path}:{f.function}" for f in in_target[-3:]]]
    else:
        last = run.frames[-1]
        where = ["assertion on target code's result failed in the main test",
                 f"assertion in the generated test at {last.function}"]
    return Verdict(outcome=O.REPRODUCED, reason=R.MATCHING_FAILURE,
                   evidence=[f"{run.exception_type}: {run.message[:200]}", *where,
                             f"pytest exit code observed by the runner: {run.exit_code}"])


def classify(runs: list[RunResult], contract: TestContract) -> Verdict:
    """Classify a set of repeated runs. REPRODUCED/NOT_REPRODUCED need unanimous agreement."""
    if not runs:
        return Verdict(outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE,
                       evidence=["no runs recorded"])
    verdicts = [_classify_run(r, contract) for r in runs]
    first = verdicts[0]
    if all(v.outcome == first.outcome and v.reason == first.reason for v in verdicts):
        return first
    # A runner error anywhere means infrastructure was not reliable.
    if any(v.outcome is O.EXECUTION_ERROR for v in verdicts):
        return next(v for v in verdicts if v.outcome is O.EXECUTION_ERROR)
    return Verdict(outcome=O.INCONCLUSIVE, reason=R.NOT_REPEATABLE,
                   evidence=[f"run outcomes differed: {[v.outcome.value for v in verdicts]}"])
