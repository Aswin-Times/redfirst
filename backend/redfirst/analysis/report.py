"""Deterministic bug-report facts: what was provided, what is missing. Nothing is invented."""

from pydantic import BaseModel, Field

from redfirst.analysis.traces import ParsedTrace, parse_traceback

_OPTIONAL_FIELDS = ("expected_behavior", "actual_behavior", "reproduction_steps",
                    "stack_trace", "environment")


class BugReportInput(BaseModel):
    """Field limits bound prompt size, and so LLM cost, for any single request."""

    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20_000)
    expected_behavior: str | None = Field(default=None, max_length=10_000)
    actual_behavior: str | None = Field(default=None, max_length=10_000)
    reproduction_steps: str | None = Field(default=None, max_length=10_000)
    stack_trace: str | None = Field(default=None, max_length=50_000)
    environment: str | None = Field(default=None, max_length=5_000)


class ReportFacts(BaseModel):
    missing_fields: list[str]
    expected_behavior_known: bool
    trace: ParsedTrace | None = None


def analyze_report(report: BugReportInput) -> ReportFacts:
    missing = [f for f in _OPTIONAL_FIELDS if not (getattr(report, f) or "").strip()]
    trace = parse_traceback(report.stack_trace) if report.stack_trace else None
    return ReportFacts(
        missing_fields=missing,
        expected_behavior_known="expected_behavior" not in missing,
        trace=trace if trace and (trace.frames or trace.exception_type) else None,
    )


def render_report(report: BugReportInput, facts: ReportFacts) -> str:
    """Plain-text report for the prompt, with missing fields stated explicitly."""
    lines = [f"Title: {report.title}", f"Description: {report.description or '(none)'}"]
    for f in _OPTIONAL_FIELDS:
        value = getattr(report, f)
        label = f.replace("_", " ").capitalize()
        lines.append(f"{label}: {value.strip() if value and value.strip() else '(not provided)'}")
    return "\n".join(lines)
