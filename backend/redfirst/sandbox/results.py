"""Turn the collector's JSON report plus runner facts into a ``RunResult``.

Generated tests must name their tests ``test_reproduces_bug`` and (optionally) ``test_control``.
"""

from typing import Any

from redfirst.domain.enums import TestPhase, TestStatus
from redfirst.verification.models import RunResult, TracebackFrame

MAIN_TEST = "test_reproduces_bug"
CONTROL_TEST = "test_control"

_PHASES = (("setup", TestPhase.SETUP), ("call", TestPhase.CALL), ("teardown", TestPhase.TEARDOWN))


def _find(tests: dict[str, Any], name: str) -> dict | None:
    matches = [rec for nodeid, rec in tests.items() if nodeid.split("::")[-1] == name]
    return matches[0] if len(matches) == 1 else None  # ambiguous or absent -> unknown


def _status(rec: dict | None) -> tuple[TestStatus, TestPhase | None, dict]:
    """Status, the phase that decided it, and that phase's detail."""
    if rec is None:
        return TestStatus.MISSING, None, {}
    phases = rec["phases"]
    for key, phase in _PHASES:
        info = phases.get(key)
        if info and info["outcome"] == "failed":
            status = TestStatus.ERROR if phase is TestPhase.SETUP else TestStatus.FAILED
            return status, phase, info
    call = phases.get("call")
    if call is None:
        skipped = phases.get("setup", {}).get("outcome") == "skipped"
        return (TestStatus.SKIPPED if skipped else TestStatus.MISSING), None, {}
    if call["outcome"] == "skipped":
        return TestStatus.SKIPPED, TestPhase.CALL, {}
    return TestStatus.PASSED, TestPhase.CALL, {}


def build_run_result(
    report: dict[str, Any] | None,
    *,
    timed_out: bool = False,
    oom_killed: bool = False,
    runner_crashed: bool = False,
) -> RunResult:
    if runner_crashed:
        return RunResult(runner_crashed=True, report_parsed=False)
    if timed_out or oom_killed:
        # A killed process may leave no (or a partial) report; do not trust it.
        return RunResult(timed_out=timed_out, oom_killed=oom_killed,
                         report_parsed=report is not None)
    if report is None:
        return RunResult(report_parsed=False)

    errors = report.get("collection_errors", [])
    if errors:
        return RunResult(collection_error=True, main_phase=TestPhase.COLLECTION,
                         message=errors[0]["message"][:500])

    tests = report.get("tests", {})
    status, phase, info = _status(_find(tests, MAIN_TEST))
    control = _find(tests, CONTROL_TEST)
    control_status = _status(control)[0] if control is not None else None
    return RunResult(
        main_status=status,
        main_phase=phase,
        control_status=control_status,
        exception_type=info.get("exception_type"),
        message=info.get("message", ""),
        frames=[TracebackFrame(**f) for f in info.get("frames", [])],
    )
