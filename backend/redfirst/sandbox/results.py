"""Turn the collector's JSON report plus runner-observed facts into a ``RunResult``.

Trust model: the report is written by a pytest plugin running *inside* the test process, the
same process that runs repository code and the generated test, so anything in that process can
rewrite it. The report is therefore parsed as untrusted input (strict schema, size limits, no
symlinks) and cross-checked against what the runner observed itself: the process exit code and
whether the run was killed. Any inconsistency is recorded in ``integrity_errors`` and the
verifier then refuses to reach a verdict about the bug.

These checks catch corruption and tampering that does not also control the exit status. They
cannot detect code that forges a consistent report *and* exits with the matching status; see
docs/threat-model.md.

Generated tests must name their tests ``test_reproduces_bug`` and (optionally) ``test_control``.
"""

import json
import os
import posixpath
import stat
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from redfirst.domain.enums import TestPhase, TestStatus
from redfirst.verification.models import RunResult, TracebackFrame
from redfirst.verification.paths import repo_relative, same_path

MAIN_TEST = "test_reproduces_bug"
CONTROL_TEST = "test_control"
GENERATED_TEST_FILE = "test_redfirst.py"
MAX_REPORT_BYTES = 256 * 1024  # the runner keeps this much (and more) of the output's tail
MAX_FRAMES = 200  # the collector keeps the innermost frames
# The container's wrapper prints the report between these markers after pytest has exited.
# {nonce} is random per run; the LAST block carrying it is the report (see extract_report_block).
REPORT_BEGIN = "@@REDFIRST-REPORT-BEGIN {nonce}@@"
REPORT_END = "@@REDFIRST-REPORT-END {nonce}@@"
PYTEST_INTERNAL_ERRORS = (3, 4)  # pytest "internal error" and "usage error" exit codes

_PHASES = (("setup", TestPhase.SETUP), ("call", TestPhase.CALL), ("teardown", TestPhase.TEARDOWN))
_IMPLIED = {0: "every test passed or was skipped", 1: "at least one test failed",
            2: "collection failed", 5: "no tests were collected"}


# -- schema of the untrusted report ------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Frame(_Strict):
    file: str = Field(max_length=4096)
    function: str = Field(max_length=512)


class _Phase(_Strict):
    outcome: Literal["passed", "failed", "skipped"]
    exception_type: str | None = Field(default=None, max_length=256)
    message: str = Field(default="", max_length=4000)
    frames: list[_Frame] = Field(default_factory=list, max_length=MAX_FRAMES)


class _Test(_Strict):
    phases: dict[Literal["setup", "call", "teardown"], _Phase]


class _CollectionError(_Strict):
    nodeid: str = Field(max_length=4096)
    message: str = Field(max_length=4000)


class CollectorReport(_Strict):
    exitstatus: int
    tests: dict[str, _Test] = Field(default_factory=dict, max_length=500)
    collection_errors: list[_CollectionError] = Field(default_factory=list, max_length=100)


# -- reading ---------------------------------------------------------------------------------
def read_report(path: Path, max_bytes: int = MAX_REPORT_BYTES) -> tuple[Any, str | None]:
    """Read the report file as untrusted input. Returns ``(data, problem)``.

    Code in the sandbox can replace the file with a symlink to a host path, so symlinks and
    non-regular files are refused rather than followed.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None, "no structured report was produced"
    except OSError as exc:
        return None, f"the report could not be inspected ({type(exc).__name__})"
    if stat.S_ISLNK(st.st_mode):
        return None, "the report path is a symlink; refusing to follow it"
    if not stat.S_ISREG(st.st_mode):
        return None, "the report path is not a regular file"
    if st.st_size > max_bytes:
        return None, f"the report is larger than {max_bytes} bytes"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return None, "the report path is not a regular file"
            raw = fh.read(max_bytes + 1)
    except OSError as exc:
        return None, f"the report could not be read ({type(exc).__name__})"
    if len(raw) > max_bytes:
        return None, f"the report is larger than {max_bytes} bytes"
    return decode_report(raw)


def decode_report(raw: bytes) -> tuple[Any, str | None]:
    """Parse report bytes as untrusted JSON. Returns ``(data, problem)``."""
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, "the report is not valid JSON"


def extract_report_block(output: bytes, nonce: str,
                         max_bytes: int = MAX_REPORT_BYTES) -> tuple[bytes | None, str | None]:
    """Find the report in the container's output. Returns ``(raw_report, problem)``.

    The wrapper prints the report after pytest (and everything it started) has exited, so the
    last block carrying this run's random nonce is authoritative. Text printed earlier by the
    code under test, including fake blocks, is ignored; blocks with another nonce never match.
    """
    begin = REPORT_BEGIN.format(nonce=nonce).encode()
    end = REPORT_END.format(nonce=nonce).encode()
    start = output.rfind(begin)
    if start < 0:
        return None, "no report block in the container's output"
    body_start = start + len(begin)
    stop = output.find(end, body_start)
    if stop < 0:
        return None, "the report block is incomplete (cut off or larger than the captured tail)"
    raw = output[body_start:stop].strip(b"\r\n")
    if len(raw) > max_bytes:
        return None, f"the report is larger than {max_bytes} bytes"
    return raw, None


def strip_report_block(text: str, nonce: str) -> str:
    """Output as shown to users: the final report block removed, everything else untouched."""
    begin = REPORT_BEGIN.format(nonce=nonce)
    end = REPORT_END.format(nonce=nonce)
    start = text.rfind(begin)
    if start < 0:
        return text
    stop = text.find(end, start)
    if stop < 0:
        return text[:start].rstrip("\r\n")
    return (text[:start].rstrip("\r\n") + text[stop + len(end):]).strip("\r\n")


# -- validation and cross-checks -----------------------------------------------------------------
def _clip(text: str, limit: int = 100) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _schema_problem(exc: ValidationError) -> str:
    # Locations and error types only: report *values* are attacker-controlled and are not echoed.
    parts = [f"{'.'.join(_clip(str(p), 60) for p in e['loc']) or '<root>'} ({e['type']})"
             for e in exc.errors()[:5]]
    return "the report is malformed: " + "; ".join(parts)


def _implied_exit_code(rep: CollectorReport) -> int:
    if rep.collection_errors:
        return 2
    if any(ph.outcome == "failed" for t in rep.tests.values() for ph in t.phases.values()):
        return 1
    return 0 if rep.tests else 5


def _inconsistencies(rep: CollectorReport, exit_code: int, test_name: str) -> list[str]:
    problems: list[str] = []
    for nodeid, test in rep.tests.items():
        path, _, func = nodeid.partition("::")
        if posixpath.basename(path.replace("\\", "/")) != test_name or not func:
            problems.append(f"the report contains a test that is not from the generated test "
                            f"file: {_clip(nodeid)}")
            continue
        setup = test.phases.get("setup")
        if setup is None:
            problems.append(f"{_clip(nodeid)} has no setup phase")
        elif "call" in test.phases and setup.outcome != "passed":
            problems.append(f"{_clip(nodeid)} ran its call phase after setup {setup.outcome}")
    for err in rep.collection_errors:
        if posixpath.basename(err.nodeid.replace("\\", "/")) != test_name:
            problems.append(f"the report contains a collection error that is not from the "
                            f"generated test file: {_clip(err.nodeid)}")
    if rep.exitstatus != exit_code:
        problems.append(f"the report says pytest exited with {rep.exitstatus}, but the runner "
                        f"observed exit code {exit_code}")
    implied = _implied_exit_code(rep)
    if implied != exit_code:
        problems.append(f"pytest exited with {exit_code}, but the report implies exit code "
                        f"{implied} ({_IMPLIED[implied]})")
    return problems


# -- interpretation ----------------------------------------------------------------------------
def _find(rep: CollectorReport, name: str) -> _Test | None:
    matches = [t for nodeid, t in rep.tests.items() if nodeid.split("::")[-1] == name]
    return matches[0] if len(matches) == 1 else None  # ambiguous or absent -> unknown


def _status(test: _Test | None) -> tuple[TestStatus, TestPhase | None, _Phase | None]:
    """Status, the phase that decided it, and that phase's detail."""
    if test is None:
        return TestStatus.MISSING, None, None
    for key, phase in _PHASES:
        info = test.phases.get(key)
        if info is not None and info.outcome == "failed":
            status = TestStatus.ERROR if phase is TestPhase.SETUP else TestStatus.FAILED
            return status, phase, info
    call = test.phases.get("call")
    if call is None:
        setup = test.phases.get("setup")
        skipped = setup is not None and setup.outcome == "skipped"
        return (TestStatus.SKIPPED if skipped else TestStatus.MISSING), None, None
    if call.outcome == "skipped":
        return TestStatus.SKIPPED, TestPhase.CALL, None
    return TestStatus.PASSED, TestPhase.CALL, None


def _frame(raw: _Frame, repo_root: str | None, test_file: str | None) -> TracebackFrame:
    in_test = bool(test_file) and same_path(raw.file, test_file)
    repo_path = None if in_test or not repo_root else repo_relative(raw.file, repo_root)
    return TracebackFrame(file=raw.file, function=raw.function, repo_path=repo_path,
                          in_generated_test=in_test)


def build_run_result(
    report: Any,
    *,
    report_problem: str | None = None,
    exit_code: int | None = None,
    timed_out: bool = False,
    oom_killed: bool = False,
    runner_crashed: bool = False,
    runner_error: str | None = None,
    output_flooded: bool = False,
    repo_root: str | None = None,
    test_file: str | None = None,
    test_name: str = GENERATED_TEST_FILE,
) -> RunResult:
    """Combine the untrusted report with facts the runner observed.

    ``repo_root`` and ``test_file`` are the repository directory and generated test file as
    seen by the test process; they decide which traceback frames count as repository code.
    """
    if runner_crashed:
        return RunResult(runner_crashed=True, runner_error=runner_error, report_parsed=False,
                         exit_code=exit_code)
    if timed_out or oom_killed or output_flooded:
        # A killed process may leave no (or a partial) report; it is not used at all.
        return RunResult(timed_out=timed_out, oom_killed=oom_killed, output_flooded=output_flooded,
                         exit_code=exit_code, report_parsed=False)
    if exit_code is None:
        return RunResult(runner_crashed=True, report_parsed=False,
                         runner_error="the runner did not observe the test process's exit code")
    if report is None:
        return RunResult(report_parsed=False, exit_code=exit_code,
                         integrity_errors=[report_problem or "no structured report was produced"])
    try:
        rep = CollectorReport.model_validate(report)
    except ValidationError as exc:
        return RunResult(report_parsed=False, exit_code=exit_code,
                         integrity_errors=[_schema_problem(exc)])
    problems = _inconsistencies(rep, exit_code, test_name)
    if problems:
        return RunResult(exit_code=exit_code, integrity_errors=problems)

    if rep.collection_errors:
        return RunResult(exit_code=exit_code, collection_error=True,
                         main_phase=TestPhase.COLLECTION,
                         message=rep.collection_errors[0].message[:500])
    status, phase, info = _status(_find(rep, MAIN_TEST))
    control = _find(rep, CONTROL_TEST)
    control_status = _status(control)[0] if control is not None else None
    return RunResult(
        exit_code=exit_code,
        main_status=status,
        main_phase=phase,
        control_status=control_status,
        exception_type=info.exception_type if info else None,
        message=info.message if info else "",
        frames=[_frame(f, repo_root, test_file) for f in (info.frames if info else [])],
    )
