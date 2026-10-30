# REDFIRST threat model

REDFIRST runs code it does not control (uploaded repositories and LLM-written tests) and sends
repository text to an LLM. This document lists the threats, the control for each, **how each
control was checked**, and what remains unaddressed. "Not verified" means the control exists in
code but has never been exercised against the real thing.

Verification legend:

- **Tested** - an automated test exercises the behaviour and passes.
- **Tested (mocked)** - tested, but with a stand-in for the real dependency (named in the row).
- **Not verified** - implemented, but never run for real.
- **None** - no control.

## Trust boundaries

| Component | Trusted? | Notes |
|---|---|---|
| API / web UI | Trusted code, **untrusted callers** | No authentication (see Residual risk 1). |
| Worker | Trusted code | Holds the Docker access and the LLM key. |
| Sandbox container | **Untrusted** | Runs repository code and generated tests. |
| Repository contents, bug report text, test output | **Untrusted data** | May contain prompt injection and secrets. |
| LLM output | **Untrusted** | Validated before execution; never decides the verdict. |

## Threats and controls

| # | Threat | Control | Verified |
|---|---|---|---|
| 1 | Archive path traversal (`../`, absolute paths, drive letters, NUL, backslashes) | Names validated before and after normalisation; every write re-checked to stay inside the destination; no `extractall` | Tested |
| 2 | Malicious symlinks, hardlinks, device files in archives | Rejected outright | Tested |
| 3 | Zip bombs, huge or deeply nested archives, name collisions | Limits on member count, depth, per-file and total bytes; compression ratio enforced beyond a 10 MB ratio-free allowance (so small, legitimately compressible archives pass); case-insensitive duplicate rejection; actual bytes counted (headers can lie); truncated archives rejected | Tested |
| 4 | Partial extraction leaving files behind | Destination removed on any failure | Tested |
| 5 | Oversized uploads | Streamed to disk with a byte limit (HTTP 413) | Tested |
| 6 | Malicious generated test (subprocess, sockets, `eval`, file writes, dynamic imports, introspection) | Static AST policy rejects before execution: imports limited to an allow-list plus the repo's own modules (`unittest` is not allowed: its patchers expose the real objects); library modules usable only as `module.name` with their public non-module API; denied names (`pytest.importorskip`, `pytest.exit`, `io.open`, `string.Formatter`, `operator.attrgetter`, `typing.get_type_hints`, ...); no `getattr`/`setattr`; no private attributes except on repository code; no fixtures that hand over pytest internals (`request`, `pytestconfig`, `cache`) and no hook-machinery attributes (`get_hookimpls`, `plugin_name`) | Tested, including every bypass found in the M9 review (they ran in real pytest before M9.1). A hygiene gate, not a boundary: **known gaps** include anything reachable through modules the repository imports. |
| 7 | Prompt injection via repo files or the bug report | Untrusted text is only ever placed in tagged data blocks in the user message, never the system message; model has no tools; the verdict comes from execution results, not model text; hostile generated code is rejected by the validator | Tested (mocked): a scripted model that obeys the injected instruction is rejected and never executed. **Not tested against a real model's resistance.** |
| 8 | LLM output deciding the result | Verdict computed by `verification/rules.py` from structured execution facts; the validator's facts override the model's claims in the contract | Tested |
| 8a | A test written so it fails whatever the repository does (`assert False`, `assert 1 == 2`, `raise AssertionError`) producing a false REPRODUCED | The validator rejects assertions in `test_reproduces_bug` that do not depend on a value returned by target code (with taint tracking through assignments, loops and `with ... as`), constant or `x and False` conditions, and `raise AssertionError`; the verifier's wrong-value allowance additionally requires the validator-set `asserts_on_target_result` flag, which since M9.2 is set only when **every** assertion is a *direct check* of a target result: `r`, `not r`, `isinstance(r, T)`, or one comparison of `r` (or `len(r)`, `r.attr`, `r[k]`, `r.method()`, ...) with a value that does not depend on target code, no `and`/chains, `is` only with `None`/`True`/`False`, never against `object()` or NaN. Assertions that mention the result but are false whatever it is (`assert r != r`, `assert [r] == []`, `y = len(r) * 0; assert y == 1`, a helper that returns a constant) still run, but their failure gives `unrelated_failure`, not REPRODUCED | Tested (unit, and end to end on a bug-free fixture: `assert False` is rejected; `r = add(2, 2); assert r != r` gave REPRODUCED before M9.2 and now gives INCONCLUSIVE). Still a heuristic: a direct comparison with a value no result can take (`assert len(r) == -1`) is not detected; and a wrong *expected value* (the bug report claims behaviour the code was never meant to have) is by definition reported as REPRODUCED, which is why the test is shown with the verdict. |
| 9 | False "REPRODUCED" from setup/import/fixture errors, unrelated failures, flaky tests | Phase-aware rules, control test, unanimous repeated runs; a traceback frame counts as target code only if its path is *inside the repository root* and equals a contract target exactly (no suffix matching: `myutils.py` never matches `utils.py`); the wrong-value allowance requires the assertion to be in the generated test file | Tested (unit, and real pytest locally) |
| 9a | Code under test tampering with the structured test report | The report is untrusted input: strict schema, size limit, nodeids must come from the generated test file; cross-checked against the exit code and OOM state read from the container runtime. Any contradiction or missing/malformed report gives `INCONCLUSIVE` / `invalid_report`, never REPRODUCED or NOT_REPRODUCED. The report reaches the host over the container's output, printed by a wrapper after pytest exits, between markers carrying a random per-run nonce; the last block wins, and the wrapper kills every other process first (shell builtin `kill -9 -1`, which needs no new process and so still works when the process limit is exhausted; since M9.2) so nothing the tests started can print after it. The nonce is not secret (readable from `/proc/1/cmdline`); only the kill makes the last block the wrapper's own | Tested with real local pytest and repositories that rewrite the report at exit. **Limitation (two strict-xfail tests document it):** a repository can rewrite the report so it is consistent with the exit status the run really had. The attacker does not need to control the exit code: a genuine failure already gives exit 1, and a forged "failed in target code" report matches it. In-process reporting cannot be made trustworthy against this. The wrapper's process-killing step and nonce handling run only in the container and are untested against real Docker. |
| 9b | A repository file named like a stdlib module (`types.py`, `re.py`) breaking pytest | Repository roots are not on `PYTHONPATH` (which precedes the stdlib); the collector plugin appends them to `sys.path` after the stdlib, and Python runs with `-P` | Tested with real local pytest; not yet in a container. |
| 10 | Infinite loops, fork bombs, memory exhaustion, disk filling, output floods | Container limits: wall-clock timeout enforced outside the container, `--pids-limit`, `--memory` with no swap, `--cpus`, `fsize` ulimit. **No writable host mount**: the repository, test and plugin mounts are read-only and `/out` and `/tmp` are size-capped tmpfs (2 MB and 64 MB), so nothing the container writes can fill a host disk. Docker's own log file is capped (`json-file`, 1 MB, 1 file). The runner reads output through bounded head+tail buffers (no unbounded memory) and stops a run printing more than 64 MB (`resource_limit`). The container is inspected before removal, so an OOM kill is reported as a resource limit | **Not verified.** Flags tested as strings; the runner's bounded reader tested with real subprocesses; lifecycle tested against a fake docker CLI; the 17 Docker tests have never run (no Docker locally; CI not yet confirmed). |
| 11 | Network exfiltration from the sandbox | `--network none` | **Not verified** (same reason) |
| 12 | Sandbox writing to the host or repo | Repo, test and plugin directories mounted read-only; **no writable host mount at all**; read-only root filesystem; non-root user; all capabilities dropped; `no-new-privileges`; no Docker socket; no secrets in the environment. The report is read from the container's output, so there is no host file to symlink-attack | Flags tested as strings; the Docker tests assert each property from inside the container (written to fail if it regresses) but **have never run** |
| 13 | Container escape | Not mitigated beyond the above. See `docs/sandbox.md`. | **None.** Docker shares the host kernel. |
| 14 | Malicious dependency install scripts | Dependencies are never installed; the sandbox has only pytest | Tested by design (no code path installs packages) |
| 15 | Credential theft from the worker's environment | Sandbox environment contains only `PYTHONPATH`, report path and one Python flag; LLM key stays in the worker | Flags tested as strings |
| 16 | Secrets printed by repo code stored or shown in logs, reports, or fed back to the model | Common token formats and secret-looking assignments are redacted from stored output, verdict evidence, and model feedback; credentials in repository files are redacted before being sent to the model | Tested. Only recognises common formats; a custom secret format will pass through. |
| 17 | LLM quota abuse | Per-report field size caps (bounded prompts); per-investigation token budget counting provider-reported usage of every attempt, including failed ones; rolling-24h cap on provider calls (calls blocked by the budget are recorded as `not_sent` and not counted); attempt limit; stops on refusals/outages instead of looping; cap on unfinished investigations (HTTP 429) | Tested. Usage the provider did not report is recorded as unknown and not counted; **not checked against the live API.** |
| 18 | Log blob path traversal | Blob keys must be exactly 64 lowercase hex characters before any path is built | Tested |
| 19 | Data retention | `DELETE /api/investigations/{id}` and `python -m redfirst.db.retention` (default 30 days) remove finished investigations, their evidence (before the execution results it references), and now-unreferenced log blobs; running ones are never deleted | Tested (SQLite with foreign keys enforced) |
| 20 | Worker crash leaving runs hanging | State persisted at every stage; each run is owned under a lease renewed by heartbeat; any worker fails runs whose lease expired (`WorkerLost`, retryable) | Tested on SQLite |
| 21 | One worker or a user overwriting another's state change (lost update), e.g. a worker undoing a cancel | Compare-and-swap state transitions (`UPDATE ... WHERE state = :expected`); a stale writer gets a conflict and stops; the API's cancel retries on a fresh read; claims are compare-and-swap from `CREATED` | Tested on SQLite, including a multi-threaded claim race. **PostgreSQL not tested.** |
| 22 | A web page reading the unauthenticated API through DNS rebinding | `TrustedHostMiddleware`: requests whose Host header is not in `REDFIRST_ALLOWED_HOSTS` (default `localhost`, `127.0.0.1`; port ignored) get HTTP 400, both in the API and in the web UI's `proxy.ts` (the UI's `/api/*` proxy rewrites the Host header, so the API alone cannot see the browser's) | Tested, including against a running stack (forged Host: 400 on pages and on `/api/*`). **Does not stop plain cross-site requests** (a page can still send simple requests such as a multipart upload or a POST to a cancel URL to `http://127.0.0.1:8000`, whose Host is allowed) and is not authentication. |

## Residual risks (not addressed)

1. **No authentication or authorisation.** Anyone who can reach the API can read every
   investigation (including source excerpts and logs), upload archives, and spend LLM budget.
   It binds to `127.0.0.1` by default. Do not expose it. This is the largest gap for any
   shared deployment; the per-investigation caps limit cost but not access.
2. **Docker is not a complete security boundary.** A kernel or runtime vulnerability can allow
   escape from a hostile repository. See `docs/sandbox.md` for stronger options.
3. **Sandbox controls have never run against a real Docker daemon** (none on the development
   machine; `.github/workflows/sandbox.yml` exists but has not run). Rows 10-12 and 15 should be
   treated as unproven until `tests/integration/test_sandbox_docker.py` passes.
3a. **Verdicts on hostile repositories can be forged** by repository code that rewrites the test
   report so it is consistent with the exit status the run really had (row 9a). The exit status
   does not have to be controlled: a genuine unrelated failure already exits 1, and a forged
   "failed inside target code" report agrees with it. The attacker is the repository's own
   author, so this misleads only about that repository; it does not by itself let the code
   escape the sandbox. Closing it needs result collection outside the process that runs the
   repository's code (for example a supervisor under another uid), which the current Docker
   settings cannot provide. Treat REPRODUCED on a repository you do not trust as a claim to
   verify by reading the executed test and running it yourself.
4. **The real LLM has never been called.** Behaviour under real prompt injection, refusals,
   truncation and rate limits is covered only by mocks.
5. **Redaction is pattern-based** and will miss unusual secret formats.
6. **Single shared database and blob store.** No per-user isolation, so no multi-tenancy.
7. **Deleting an investigation does not delete its repository** (archives are reused across
   investigations); remove repositories manually if required.
8. **Timing side channels, resource contention between concurrent sandboxes, and
   denial of service against the API itself** (beyond the queue cap) are not addressed.
