"""Pytest plugin that records per-phase outcomes as JSON.

Runs *inside* the sandbox, so it must not import anything from ``redfirst``. The output path
comes from the REDFIRST_REPORT_PATH environment variable. Load with ``-p collector_plugin``.

Everything this plugin writes can be rewritten by the code under test, which runs in the same
process; the runner treats the report as untrusted (see redfirst/sandbox/results.py).
"""

import json
import os

import pytest

MAX_FRAMES = 200  # keep the innermost frames; must match results.MAX_FRAMES
MAX_MESSAGE = 2000

_records: dict[str, dict] = {}
_collection_errors: list[dict] = []


def _frames(excinfo) -> list[dict]:
    out = []
    for entry in excinfo.traceback:
        try:
            out.append({"file": str(entry.path), "function": entry.name})
        except Exception:  # a frame we cannot describe must not break reporting
            continue
    return out[-MAX_FRAMES:]


def _text(value) -> str:
    try:
        return str(value)[:MAX_MESSAGE]
    except Exception:  # an exception whose __str__ fails must not break reporting
        return "<unprintable exception>"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    rec = _records.setdefault(item.nodeid, {"phases": {}})
    phase = {"outcome": report.outcome}
    if call.excinfo is not None:
        phase.update(
            exception_type=call.excinfo.type.__name__,
            message=_text(call.excinfo.value),
            frames=_frames(call.excinfo),
        )
    rec["phases"][report.when] = phase
    return report


def pytest_collectreport(report):
    if report.failed:
        _collection_errors.append({"nodeid": report.nodeid, "message": _text(report.longrepr)})


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("REDFIRST_REPORT_PATH")
    if not path:
        return
    payload = {
        "exitstatus": int(exitstatus),
        "tests": _records,
        "collection_errors": _collection_errors,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
