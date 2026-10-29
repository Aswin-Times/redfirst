"""Pytest plugin that records per-phase outcomes as JSON.

Runs *inside* the sandbox, so it must not import anything from ``redfirst``. The output path
comes from the REDFIRST_REPORT_PATH environment variable. Load with ``-p collector_plugin``.
"""

import json
import os

import pytest

_records: dict[str, dict] = {}
_collection_errors: list[dict] = []


def _frames(excinfo) -> list[dict]:
    out = []
    for entry in excinfo.traceback:
        try:
            out.append({"file": str(entry.path), "function": entry.name})
        except Exception:  # a frame we cannot describe must not break reporting
            continue
    return out


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    rec = _records.setdefault(item.nodeid, {"phases": {}})
    phase = {"outcome": report.outcome}
    if call.excinfo is not None:
        phase.update(
            exception_type=call.excinfo.type.__name__,
            message=str(call.excinfo.value)[:2000],
            frames=_frames(call.excinfo),
        )
    rec["phases"][report.when] = phase
    return report


def pytest_collectreport(report):
    if report.failed:
        _collection_errors.append({"nodeid": report.nodeid, "message": str(report.longrepr)[:2000]})


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
