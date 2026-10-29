"""Deterministic outcome classification. No LLM involvement.

Rules are evaluated in order; the first match decides.
"""

from redfirst.domain.enums import Outcome as O
from redfirst.domain.enums import OutcomeReason as R
from redfirst.domain.enums import TestPhase, TestStatus
from redfirst.verification.models import RunResult, TestContract, Verdict


def _signature_matches(run: RunResult, contract: TestContract) -> bool:
    sig = contract.expected_signature
    if sig.exception_type is None and sig.message_contains is None:
        return False  # an empty signature can never confirm a defect
    if sig.exception_type and run.exception_type != sig.exception_type:
        return False
    return not (sig.message_contains and sig.message_contains not in run.message)


def _hits_target(run: RunResult, contract: TestContract) -> bool:
    targets = [t.replace("\\", "/") for t in contract.target_modules]
    return any(f.file.replace("\\", "/").endswith(t) for f in run.frames for t in targets)


def _classify_run(run: RunResult, contract: TestContract) -> Verdict:
    if run.runner_crashed or not run.report_parsed:
        return Verdict(outcome=O.EXECUTION_ERROR, reason=R.RUNNER_FAILURE,
                       evidence=["runner crashed or produced no parseable report"])
    if run.collection_error or run.main_phase in (TestPhase.COLLECTION, TestPhase.SETUP):
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.SETUP_FAILURE,
                       evidence=[f"failure before the test body ran: {run.message[:200]}"])
    if run.timed_out or run.oom_killed:
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.RESOURCE_LIMIT,
                       evidence=["timeout" if run.timed_out else "out of memory"])
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
    if not _hits_target(run, contract):
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.UNRELATED_FAILURE,
                       evidence=["no traceback frame in a target module"])
    if not _signature_matches(run, contract):
        return Verdict(outcome=O.INCONCLUSIVE, reason=R.SIGNATURE_MISMATCH,
                       evidence=[f"got {run.exception_type}: {run.message[:200]}"])
    return Verdict(outcome=O.REPRODUCED, reason=R.MATCHING_FAILURE,
                   evidence=[f"{run.exception_type}: {run.message[:200]}",
                             *[f"frame {f.file}:{f.function}" for f in run.frames[-3:]]])


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
