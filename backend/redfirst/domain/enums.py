"""Status and outcome enums shared across REDFIRST."""

from enum import StrEnum


class InvestigationState(StrEnum):
    CREATED = "CREATED"
    ANALYZING_REPORT = "ANALYZING_REPORT"
    ANALYZING_REPOSITORY = "ANALYZING_REPOSITORY"
    GENERATING_TEST = "GENERATING_TEST"
    VALIDATING_TEST = "VALIDATING_TEST"
    EXECUTING_TEST = "EXECUTING_TEST"
    VERIFYING_RESULT = "VERIFYING_RESULT"
    COMPLETED = "COMPLETED"  # terminal; carries an Outcome
    FAILED = "FAILED"  # terminal; infrastructure failure (Outcome.EXECUTION_ERROR)
    CANCELLED = "CANCELLED"  # terminal


class Outcome(StrEnum):
    REPRODUCED = "REPRODUCED"
    NOT_REPRODUCED = "NOT_REPRODUCED"
    INCONCLUSIVE = "INCONCLUSIVE"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class OutcomeReason(StrEnum):
    """Machine-readable reason attached to every outcome."""

    MATCHING_FAILURE = "matching_failure"
    NO_FAILURE_OBSERVED = "no_failure_observed"
    RUNNER_FAILURE = "runner_failure"
    SETUP_FAILURE = "setup_failure"
    CONTROL_FAILED = "control_failed"
    RESOURCE_LIMIT = "resource_limit"
    UNRELATED_FAILURE = "unrelated_failure"
    SIGNATURE_MISMATCH = "signature_mismatch"
    NOT_REPEATABLE = "not_repeatable"
    NO_EXPECTED_BEHAVIOR = "no_expected_behavior"
    TARGET_NOT_EXERCISED = "target_not_exercised"
    GENERATION_EXHAUSTED = "generation_exhausted"
    MODEL_REFUSED = "model_refused"
    INVALID_REPORT = "invalid_report"  # report missing, malformed, or contradicts the runner
    UNCLASSIFIABLE = "unclassifiable"


class TestPhase(StrEnum):
    __test__ = False  # not a pytest class

    COLLECTION = "collection"
    SETUP = "setup"
    CALL = "call"
    TEARDOWN = "teardown"


class TestStatus(StrEnum):
    __test__ = False

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    MISSING = "missing"  # test never reported
