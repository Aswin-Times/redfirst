# How REDFIRST decides the outcome

The outcome is computed by `backend/redfirst/verification/rules.py` from structured facts. The
LLM never sets it. A failing test is **not** automatically a reproduction.

## Inputs

For each sandbox run, a pytest plugin (`sandbox/collector_plugin.py`) records the outcome of
each phase (setup, call, teardown), the exception type and message, and the traceback frames.
`sandbox/results.py` turns that into a `RunResult`. The generated test must define:

- `test_reproduces_bug` - asserts the **expected** behavior; it should fail if the bug exists.
- `test_control` (recommended) - same setup, a known-good input; it must pass.

The test also declares a *contract*: which repository files it targets and the exception it
predicts. The static validator (not the model) sets whether the test actually calls target
code and whether a control test exists.

## Rules, in order (first match wins, per run)

| # | Condition | Outcome / reason |
|---|---|---|
| 1 | Runner crashed, or no parseable report (and the run was not killed) | EXECUTION_ERROR / runner_failure |
| 2 | Collection error, or failure in setup (import error, broken fixture) | INCONCLUSIVE / setup_failure |
| 3 | Timed out or out of memory | INCONCLUSIVE / resource_limit |
| 4 | Main test missing or skipped | INCONCLUSIVE / unclassifiable |
| 5 | Control test declared but did not pass | INCONCLUSIVE / control_failed |
| 6 | Report gave no expected behavior | INCONCLUSIVE / no_expected_behavior |
| 7 | Main test passed, target not shown to be exercised | INCONCLUSIVE / target_not_exercised |
| 8 | Main test passed | NOT_REPRODUCED / no_failure_observed |
| 9 | Failure outside the call phase | INCONCLUSIVE / unrelated_failure |
| 10 | Failure with no traceback frame in a target file, unless it is a wrong-value assertion (below) | INCONCLUSIVE / unrelated_failure |
| 11 | Exception type or message differs from the contract's prediction (an empty prediction never matches) | INCONCLUSIVE / signature_mismatch |
| 12 | Otherwise | **REPRODUCED** / matching_failure |

**Wrong-value bugs.** A function that returns the wrong value fails on the test's own
`assert`, not inside the target code. Rule 10 accepts this only when an `AssertionError` was
both predicted and observed, it was raised directly in `test_reproduces_bug`, the validator
confirmed that test calls target code, and the control test passed. The report states which
kind of evidence was used, because it is weaker than a failure inside target code.

## Repeated runs

The test runs up to `REDFIRST_REPRODUCTION_RUNS` times (default 3). Runs that cannot test the
bug (setup failures, crashes) are not repeated. The final outcome requires every run to agree
on outcome and reason; any runner error dominates; disagreement is
INCONCLUSIVE / not_repeatable.

## Non-run outcomes

| Situation | Result |
|---|---|
| No valid test after the attempt limit, or the model keeps repeating the same rejected test | INCONCLUSIVE / generation_exhausted |
| Model refused the request | INCONCLUSIVE / model_refused |
| LLM outage, rate limit, budget exhausted, sandbox unavailable, unexpected error | FAILED state, outcome EXECUTION_ERROR (retryable where applicable) |
| User cancelled | CANCELLED, no outcome |

## What an outcome does and does not mean

- **REPRODUCED** - the executed test showed behavior matching the report, with the evidence
  listed in the report. Read the test before relying on it.
- **NOT_REPRODUCED** - the test ran meaningfully and the bug did not appear under the tested
  conditions. It does **not** prove the bug is absent.
- **INCONCLUSIVE** - the attempt could not establish either way; the reason says why.
- **EXECUTION_ERROR** - REDFIRST itself failed; nothing is concluded about the bug.

Every rule above has a unit test in `backend/tests/unit/test_rules.py`; the end-to-end tests
exercise them on fixture repositories with known behavior.
