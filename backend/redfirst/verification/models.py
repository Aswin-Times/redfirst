"""Structured inputs and outputs of the verification engine."""

from pydantic import BaseModel, Field

from redfirst.domain.enums import Outcome, OutcomeReason, TestPhase, TestStatus


class FailureSignature(BaseModel):
    """What the bug, if present, should look like when the test runs."""

    exception_type: str | None = None  # e.g. "AssertionError", "KeyError"
    message_contains: str | None = None


class TestContract(BaseModel):
    """Declared by the generated test; checked by the validator and the verifier."""

    __test__ = False

    target_modules: list[str] = Field(min_length=1)  # module paths, e.g. "app/users.py"
    expected_signature: FailureSignature
    has_control_test: bool = False
    exercises_target: bool = False  # set by the validator (AST), not by the model
    # Set by the validator: every assertion in test_reproduces_bug depends on a target result,
    # so an AssertionError raised by it is evidence about the target (wrong-value bugs).
    asserts_on_target_result: bool = False
    expected_behavior_known: bool = True  # False if the report gave no checkable expectation


class TracebackFrame(BaseModel):
    file: str  # as reported by the test process; shown in evidence, never matched directly
    function: str
    # Set by the trusted runner from known roots (see verification/paths.py):
    repo_path: str | None = None  # path relative to the repository root; None if outside it
    in_generated_test: bool = False  # frame is in the generated test file itself


class RunResult(BaseModel):
    """Parsed facts from one sandbox run. Built by the runner, never by the LLM.

    The collector report comes from inside the test process and is untrusted; the runner
    cross-checks it against facts it observed itself (exit code, kills). Any problem is listed
    in ``integrity_errors`` and the verifier then refuses to reach a verdict about the bug.
    """

    runner_crashed: bool = False
    runner_error: str | None = None
    report_parsed: bool = True
    integrity_errors: list[str] = Field(default_factory=list)
    exit_code: int | None = None  # observed by the runner, not taken from the report
    timed_out: bool = False
    oom_killed: bool = False
    output_flooded: bool = False  # the run printed more than the runner's hard output cap
    collection_error: bool = False
    main_status: TestStatus = TestStatus.MISSING
    main_phase: TestPhase | None = None
    control_status: TestStatus | None = None
    exception_type: str | None = None
    message: str = ""
    frames: list[TracebackFrame] = Field(default_factory=list)


class Verdict(BaseModel):
    outcome: Outcome
    reason: OutcomeReason
    evidence: list[str] = Field(default_factory=list)
