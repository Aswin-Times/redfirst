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

### The report is untrusted; runner facts are not

The report comes from inside the test process, where the code under test can rewrite it. It reaches the host as text printed by a container wrapper after pytest exits, between markers carrying a random per-run nonce (the last such block wins). The
runner therefore also records facts it observes itself: the exit code and OOM flag from the
container runtime, and whether it had to kill the run. Before any rule below looks at test
outcomes, the report must pass a strict schema and agree with those facts:

| pytest exit code | Report must show |
|---|---|
| 0 | every test passed or was skipped |
| 1 | at least one failed phase (setup, call or teardown) |
| 2 | a collection error |
| 5 | no tests collected |

The report's own `exitstatus` must equal the observed exit code; every test must come from the
generated test file and have a coherent phase sequence. Any mismatch is recorded as an
integrity error. An integrity error never contributes test outcomes.

### Which frames are target code

Each traceback frame is mapped by the runner to a path relative to the repository root *as
seen by the test process* (`/repo` in Docker). A frame counts as target code only if it lies
inside that root and its relative path equals a contract target exactly. Library files, installed
copies and look-alike names (`myutils.py` vs `utils.py`) never match. Separators and Windows
drive-letter case are normalised; targets that are absolute or escape the root never match.

## Rules, in order (first match wins, per run)

| # | Condition | Outcome / reason |
|---|---|---|
| 1 | The runner could not run the test (Docker failure, no observed exit code) | EXECUTION_ERROR / runner_failure |
| 2 | Timed out or out of memory (judged on the kill; the report is ignored) | INCONCLUSIVE / resource_limit |
| 3 | Report missing, malformed, or contradicting the runner's facts, and pytest exited 3 or 4 (internal or usage error) | EXECUTION_ERROR / runner_failure |
| 4 | Report missing, malformed, or contradicting the runner's facts (any other exit code) | INCONCLUSIVE / invalid_report |
| 5 | Collection error, or failure in setup (import error, broken fixture) | INCONCLUSIVE / setup_failure |
| 6 | Main test missing or skipped | INCONCLUSIVE / unclassifiable |
| 7 | Control test declared but did not pass | INCONCLUSIVE / control_failed |
| 8 | Report gave no expected behavior | INCONCLUSIVE / no_expected_behavior |
| 9 | Main test passed, target not shown to be exercised | INCONCLUSIVE / target_not_exercised |
| 10 | Main test passed | NOT_REPRODUCED / no_failure_observed |
| 11 | Failure outside the call phase | INCONCLUSIVE / unrelated_failure |
| 12 | Failure with no frame in a target file inside the repository, unless it is a wrong-value assertion (below) | INCONCLUSIVE / unrelated_failure |
| 13 | Exception type or message differs from the contract's prediction (an empty prediction never matches) | INCONCLUSIVE / signature_mismatch |
| 14 | Otherwise | **REPRODUCED** / matching_failure |

Changed in M9: a missing report after a normal exit used to be EXECUTION_ERROR; it is now
INCONCLUSIVE / invalid_report (rule 4), because the code under test can delete or corrupt the
report, so its absence is not evidence of an infrastructure failure. Pytest internal and usage
errors (rule 3) still count as runner failures.

**Wrong-value bugs.** A function that returns the wrong value fails on the test's own
`assert`, not inside the target code. Rule 12 accepts this only when all of these hold: an
`AssertionError` was both predicted and observed; it was raised directly in
`test_reproduces_bug` *in the generated test file*; the validator confirmed the test calls
target code; and the validator confirmed that **every assertion in the main test depends on a
value returned by target code** (`asserts_on_target_result`). The last condition exists because
a test that fails whatever the repository does (`assert False`, `assert 1 == 2`,
`raise AssertionError`) would otherwise count as a reproduction on a bug-free repository; such
tests are rejected before they run. The check is a heuristic (it follows names assigned from
target calls through assignments, loops and `with ... as`) and cannot tell an assertion that
mentions a result but is still always false. The report states which kind of evidence was used,
because it is weaker than a failure inside target code.

## Repeated runs

The test runs up to `REDFIRST_REPRODUCTION_RUNS` times (default 3). Runs that cannot test the
bug (setup failures, crashes, untrusted reports) are not repeated, and an invalid report does
not trigger regeneration. The final outcome requires every run to agree on outcome and reason;
any runner error dominates; disagreement is INCONCLUSIVE / not_repeatable. The verdict evidence
record links to the execution results it was derived from.

## Non-run outcomes

| Situation | Result |
|---|---|
| No valid test after the attempt limit, or the model keeps repeating the same rejected test | INCONCLUSIVE / generation_exhausted |
| Model refused the request | INCONCLUSIVE / model_refused |
| LLM outage, rate limit, budget exhausted, sandbox unavailable, unexpected error | FAILED state, outcome EXECUTION_ERROR (retryable where applicable) |
| The worker's lease expired (it crashed or stalled) | FAILED state, EXECUTION_ERROR, `WorkerLost` (retryable) |
| User cancelled | CANCELLED, no outcome; a worker that was mid-run stops without overwriting it |

## What an outcome does and does not mean

- **REPRODUCED** - the executed test showed behavior matching the report, with the evidence
  listed in the report. Read the test before relying on it.
- **NOT_REPRODUCED** - the test ran meaningfully and the bug did not appear under the tested
  conditions. It does **not** prove the bug is absent.
- **INCONCLUSIVE** - the attempt could not establish either way; the reason says why.
- **EXECUTION_ERROR** - REDFIRST itself failed; nothing is concluded about the bug.

Every rule above has a unit test in `backend/tests/unit/test_rules.py`; the end-to-end tests
exercise them on fixture repositories with known behavior.
