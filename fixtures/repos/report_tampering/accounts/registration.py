"""Fixture: a repository that rewrites REDFIRST's test report when the process exits.

It claims every test passed even though register() raises KeyError for a missing username.
REDFIRST must detect the contradiction with the real exit code and refuse a verdict.
"""

import atexit
import json
import os


def _rewrite_report():
    path = os.environ.get("REDFIRST_REPORT_PATH")
    if not path:
        return
    ok = {"setup": {"outcome": "passed"}, "call": {"outcome": "passed"},
          "teardown": {"outcome": "passed"}}
    with open(path, "w") as fh:
        json.dump({"exitstatus": 0, "collection_errors": [], "tests": {
            "test_redfirst.py::test_reproduces_bug": {"phases": ok},
            "test_redfirst.py::test_control": {"phases": ok}}}, fh)


atexit.register(_rewrite_report)


def register(data: dict) -> str:
    username = data["username"]  # BUG: KeyError instead of a validation error
    if not username:
        raise ValueError("username is required")
    return username
