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
    expected_behavior_known: bool = True  # False if the report gave no checkable expectation


class TracebackFrame(BaseModel):
    file: str
    function: str


class RunResult(BaseModel):
    """Parsed facts from one sandbox run. Built by the runner, never by the LLM."""

    runner_crashed: bool = False
    report_parsed: bool = True
    timed_out: bool = False
    oom_killed: bool = False
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
