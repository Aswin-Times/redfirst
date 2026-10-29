"""Bounded generate -> validate -> repair loop. No unbounded agent behaviour."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from redfirst.llm.base import LLMError, LLMInvalidOutput, LLMProvider
from redfirst.llm.prompts import PromptTemplate
from redfirst.validation.policy import ALLOWED_LIBRARIES, ValidationResult, validate_test
from redfirst.verification.models import FailureSignature, TestContract


class GeneratedTestOutput(BaseModel):
    """Structured output the model must return."""

    test_code: str = Field(description="Complete pytest module")
    target_modules: list[str] = Field(description="Repository file paths under test")
    expected_exception_type: str | None = Field(
        description="Exception class name expected when the bug is present")
    expected_message_contains: str | None = Field(
        description="Substring expected in the failure message, or null")
    strategy: str = Field(description="One or two sentences on how the test reproduces the bug")
    assumptions: list[str] = Field(description="Assumptions made where the report was silent")


@dataclass
class AttemptRecord:
    number: int
    output: GeneratedTestOutput | None = None
    validation: ValidationResult | None = None
    llm_metadata: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class GenerationOutcome:
    attempts: list[AttemptRecord] = field(default_factory=list)
    accepted: AttemptRecord | None = None
    stop_reason: str = ""  # accepted | attempts_exhausted | repeated_failure | llm_<error type>
    retryable: bool = False  # True when stopped by a transient provider failure


def _feedback(record: AttemptRecord) -> str:
    if record.error:
        return f"<previous_attempt_problem>\n{record.error}\n</previous_attempt_problem>\n"
    assert record.validation is not None
    problems = "\n".join(f"- {e}" for e in record.validation.errors)
    return ("<previous_attempt_rejected>\nYour previous test was rejected by the validator "
            f"and was not run:\n{problems}\nFix these problems.\n</previous_attempt_rejected>\n")


def generate_test(
    provider: LLMProvider,
    prompt: PromptTemplate,
    *,
    report_text: str,
    evidence_text: str,
    modules: dict[str, str],
    max_attempts: int,
) -> GenerationOutcome:
    outcome = GenerationOutcome()
    feedback = ""
    last_problems: tuple[str, ...] | None = None
    for number in range(1, max_attempts + 1):
        record = AttemptRecord(number=number)
        outcome.attempts.append(record)
        request = prompt.render(
            report=report_text, evidence=evidence_text, feedback=feedback,
            allowed_imports=", ".join(sorted(ALLOWED_LIBRARIES)),
        )
        try:
            result = provider.generate(request, GeneratedTestOutput)
        except LLMInvalidOutput as exc:  # counts as an attempt; may succeed on retry
            record.error = f"invalid model output: {exc}"
            problems: tuple[str, ...] = (record.error,)
        except LLMError as exc:  # refusal, rejection, outage: stop, never loop on these
            record.error = f"{type(exc).__name__}: {exc}"
            outcome.stop_reason = f"llm_{type(exc).__name__}"
            outcome.retryable = exc.retryable
            return outcome
        else:
            record.output = result.output
            record.llm_metadata = result.metadata(request)
            record.validation = validate_test(result.output.test_code, modules,
                                              result.output.target_modules)
            if record.validation.ok:
                outcome.accepted = record
                outcome.stop_reason = "accepted"
                return outcome
            problems = tuple(record.validation.errors)

        if problems == last_problems:  # the model is not making progress
            outcome.stop_reason = "repeated_failure"
            return outcome
        last_problems = problems
        feedback = _feedback(record)
    outcome.stop_reason = "attempts_exhausted"
    return outcome


def to_contract(
    output: GeneratedTestOutput, validation: ValidationResult, expected_behavior_known: bool
) -> TestContract:
    """Combine model claims with validator-established facts. The validator wins."""
    return TestContract(
        target_modules=output.target_modules,
        expected_signature=FailureSignature(
            exception_type=output.expected_exception_type,
            message_contains=output.expected_message_contains,
        ),
        has_control_test=validation.has_control_test,
        exercises_target=validation.exercises_target,
        expected_behavior_known=expected_behavior_known,
    )
