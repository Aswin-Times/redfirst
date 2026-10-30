"""M9.1 R3: the report travels over the container's stdout between nonce-tagged markers, and the
runner reads container output through a bounded capture. No writable host mount is involved.
"""

import json
import sys
import threading
import time
import tracemalloc

import pytest

from redfirst.domain.enums import Outcome as O
from redfirst.domain.enums import OutcomeReason as R
from redfirst.sandbox.results import (
    MAX_REPORT_BYTES,
    REPORT_BEGIN,
    REPORT_END,
    build_run_result,
    extract_report_block,
    strip_report_block,
)
from redfirst.sandbox.runner import run_bounded
from redfirst.verification.models import FailureSignature, TestContract
from redfirst.verification.rules import classify

NONCE = "0123456789abcdef0123456789abcdef"
OTHER = "ffffffffffffffffffffffffffffffff"
CONTRACT = TestContract(target_modules=["app/users.py"],
                        expected_signature=FailureSignature(exception_type="KeyError"),
                        exercises_target=True)


def block(payload: str, nonce: str = NONCE) -> bytes:
    begin, end = REPORT_BEGIN.format(nonce=nonce), REPORT_END.format(nonce=nonce)
    return f"\n{begin}\n{payload}\n{end}\n".encode()


# --- locating the report in the output --------------------------------------------------------
def test_report_block_is_extracted_from_the_end_of_the_output():
    out = b"collected 2 items\n.F\n" + block('{"a": 1}')
    assert extract_report_block(out, NONCE) == (b'{"a": 1}', None)


def test_the_last_block_with_the_right_nonce_wins():
    """Code under test can print its own markers; the wrapper always prints last."""
    forged = block('{"forged": true}')
    out = forged + b"more test output\n" + block('{"real": true}')
    assert extract_report_block(out, NONCE)[0] == b'{"real": true}'


def test_blocks_with_a_different_nonce_are_ignored():
    out = block('{"real": 1}') + block('{"guess": 1}', nonce=OTHER)
    assert extract_report_block(out, NONCE)[0] == b'{"real": 1}'


def test_missing_block_is_reported_not_guessed():
    data, problem = extract_report_block(b"just output", NONCE)
    assert data is None and "no report block" in problem


def test_incomplete_block_is_reported_as_too_large_or_cut_off():
    out = b"x" + f"\n{REPORT_BEGIN.format(nonce=NONCE)}\n".encode() + b'{"partial": '
    data, problem = extract_report_block(out, NONCE)
    assert data is None and "incomplete" in problem


def test_oversized_report_block_is_refused():
    payload = "x" * (MAX_REPORT_BYTES + 10)
    data, problem = extract_report_block(block(payload), NONCE)
    assert data is None and "larger than" in problem


def test_a_forged_end_marker_inside_the_report_cannot_extend_it():
    out = block('{"a": 1}') + b'trailing {"b": 2}\n'
    assert extract_report_block(out, NONCE)[0] == b'{"a": 1}'


def test_strip_removes_only_the_final_block_from_displayed_output():
    out = b"line one\n" + block('{"a": 1}')
    shown = strip_report_block(out.decode(), NONCE)
    assert "line one" in shown and "REDFIRST-REPORT" not in shown and '"a"' not in shown
    forged = block('{"forged": 1}') + b"tail\n" + block('{"real": 1}')
    shown = strip_report_block(forged.decode(), NONCE)
    assert "forged" in shown and "real" not in shown  # the attacker's text stays visible as output


def test_the_runner_builds_results_from_the_extracted_block():
    report = {"exitstatus": 0, "collection_errors": [], "tests": {}}
    raw, problem = extract_report_block(block(json.dumps(report)), NONCE)
    assert problem is None
    parsed = json.loads(raw)
    r = build_run_result(parsed, exit_code=5, repo_root="/repo", test_file="/gen/test_redfirst.py")
    assert r.integrity_errors  # exitstatus 0 vs observed 5 contradicts: fails closed


# --- output flood: a bounded, streaming reader -----------------------------------------------
PRINTER = ("import sys\nchunk = 'x' * 1000 + chr(10)\n"
           "for _ in range({n}):\n    sys.stdout.write(chunk)\n")


def test_small_output_is_kept_whole():
    code = "print('hello'); import sys; sys.stderr.write('oops')"
    cap = run_bounded([sys.executable, "-c", code], timeout=30)
    assert cap.returncode == 0 and b"hello" in cap.stdout and b"oops" in cap.stderr
    assert not cap.truncated and not cap.flooded and not cap.timed_out


def test_large_output_keeps_the_head_and_the_tail_and_a_bounded_amount_of_memory():
    code = PRINTER.format(n=20_000) + "print('THE-END-MARKER')\n"  # ~20 MB
    tracemalloc.start()
    cap = run_bounded([sys.executable, "-c", code], timeout=60, head_bytes=64 * 1024,
                      tail_bytes=64 * 1024, hard_cap_bytes=64 * 1024 * 1024)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert cap.truncated and not cap.flooded
    assert cap.stdout.startswith(b"x" * 100)                 # head kept
    assert b"THE-END-MARKER" in cap.stdout[-200:]            # tail kept
    assert len(cap.stdout) < 140 * 1024                      # bounded
    assert peak < 8 * 1024 * 1024, f"buffered {peak} bytes"  # did not buffer 20 MB


def test_an_endless_printer_is_cut_off_at_the_hard_cap():
    code = "import sys\nwhile True:\n    sys.stdout.write('y' * 4096)\n"
    started = time.monotonic()
    cap = run_bounded([sys.executable, "-c", code], timeout=60, head_bytes=1024, tail_bytes=1024,
                      hard_cap_bytes=2 * 1024 * 1024)
    assert cap.flooded and not cap.timed_out
    assert time.monotonic() - started < 30
    assert len(cap.stdout) < 8 * 1024


def test_timeout_is_reported_and_the_process_stopped():
    cap = run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], timeout=1)
    assert cap.timed_out and cap.returncode is None


def test_stderr_floods_are_bounded_too():
    code = "import sys\nwhile True:\n    sys.stderr.write('e' * 4096)\n"
    cap = run_bounded([sys.executable, "-c", code], timeout=60, head_bytes=1024, tail_bytes=1024,
                      hard_cap_bytes=2 * 1024 * 1024)
    assert cap.flooded and len(cap.stderr) < 8 * 1024


def test_reader_threads_do_not_leak():
    before = threading.active_count()
    run_bounded([sys.executable, "-c", "print('x')"], timeout=30)
    time.sleep(0.2)
    assert threading.active_count() <= before


def test_missing_executable_raises_a_clear_error():
    with pytest.raises(FileNotFoundError):
        run_bounded(["definitely-not-a-real-command-xyz"], timeout=5)


# --- the verifier treats a flood as a resource limit -----------------------------------------
def test_output_flood_is_inconclusive_resource_limit():
    r = build_run_result(None, exit_code=137, output_flooded=True)
    assert r.output_flooded
    v = classify([r], CONTRACT)
    assert (v.outcome, v.reason) == (O.INCONCLUSIVE, R.RESOURCE_LIMIT)
    assert any("output" in e for e in v.evidence)
