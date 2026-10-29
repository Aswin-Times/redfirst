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
| 3 | Zip bombs, huge or deeply nested archives, name collisions | Limits on member count, depth, per-file and total bytes, compression ratio; case-insensitive duplicate rejection; actual bytes counted (headers can lie) | Tested |
| 4 | Partial extraction leaving files behind | Destination removed on any failure | Tested |
| 5 | Oversized uploads | Streamed to disk with a byte limit (HTTP 413) | Tested |
| 6 | Malicious generated test (subprocess, sockets, `eval`, dunder escapes) | Static AST policy rejects before execution; imports limited to an allow-list plus the repo's own modules | Tested. A static check is a hygiene gate, not a boundary: it can be evaded. |
| 7 | Prompt injection via repo files or the bug report | Untrusted text is only ever placed in tagged data blocks in the user message, never the system message; model has no tools; the verdict comes from execution results, not model text; hostile generated code is rejected by the validator | Tested (mocked): a scripted model that obeys the injected instruction is rejected and never executed. **Not tested against a real model's resistance.** |
| 8 | LLM output deciding the result | Verdict computed by `verification/rules.py` from structured execution facts; the validator's facts override the model's claims in the contract | Tested |
| 9 | False "REPRODUCED" from setup/import/fixture errors, unrelated failures, flaky tests | Phase-aware rules, control test, target-code traceback check, unanimous repeated runs | Tested (real pytest, local) |
| 10 | Infinite loops, fork bombs, memory exhaustion, disk filling | Container limits: wall-clock timeout enforced outside the container, `--pids-limit`, `--memory` with no swap, `--cpus`, tmpfs size cap, `fsize` ulimit, output truncated | **Not verified.** The flags are unit-tested as strings; the 7 abuse tests need Docker and have never run. |
| 11 | Network exfiltration from the sandbox | `--network none` | **Not verified** (same reason) |
| 12 | Sandbox writing to the host or repo | Repo mounted read-only; only one writable mount (the report directory); read-only root filesystem; non-root user; all capabilities dropped; `no-new-privileges`; no Docker socket; no secrets in the environment | Flags tested as strings; **runtime behaviour not verified** |
| 13 | Container escape | Not mitigated beyond the above. See `docs/sandbox.md`. | **None.** Docker shares the host kernel. |
| 14 | Malicious dependency install scripts | Dependencies are never installed; the sandbox has only pytest | Tested by design (no code path installs packages) |
| 15 | Credential theft from the worker's environment | Sandbox environment contains only `PYTHONPATH`, report path and one Python flag; LLM key stays in the worker | Flags tested as strings |
| 16 | Secrets printed by repo code stored or shown in logs, reports, or fed back to the model | Common token formats and secret-looking assignments are redacted from stored output, verdict evidence, and model feedback; credentials in repository files are redacted before being sent to the model | Tested. Only recognises common formats; a custom secret format will pass through. |
| 17 | LLM quota abuse | Per-report field size caps (bounded prompts); per-investigation token budget; rolling-24h cap on LLM calls; attempt limit; stops on refusals/outages instead of looping; cap on unfinished investigations (HTTP 429) | Tested. Token counts come from the provider's usage; **not checked against the live API.** |
| 18 | Log blob path traversal | Blob keys must be exactly 64 lowercase hex characters before any path is built | Tested |
| 19 | Data retention | `DELETE /api/investigations/{id}` and `python -m redfirst.db.retention` (default 30 days) remove finished investigations and now-unreferenced log blobs; running ones are never deleted | Tested |
| 20 | Worker crash leaving runs hanging | State persisted at every stage; on start, mid-pipeline runs are marked FAILED (`WorkerLost`) | Tested |

## Residual risks (not addressed)

1. **No authentication or authorisation.** Anyone who can reach the API can read every
   investigation (including source excerpts and logs), upload archives, and spend LLM budget.
   It binds to `127.0.0.1` by default. Do not expose it. This is the largest gap for any
   shared deployment; the per-investigation caps limit cost but not access.
2. **Docker is not a complete security boundary.** A kernel or runtime vulnerability can allow
   escape from a hostile repository. See `docs/sandbox.md` for stronger options.
3. **Sandbox controls have never run against a real Docker daemon** (none on the development
   machine). Rows 10-12 and 15 should be treated as unproven until
   `tests/integration/test_sandbox_docker.py` passes.
4. **The real LLM has never been called.** Behaviour under real prompt injection, refusals,
   truncation and rate limits is covered only by mocks.
5. **Redaction is pattern-based** and will miss unusual secret formats.
6. **Single shared database and blob store.** No per-user isolation, so no multi-tenancy.
7. **Deleting an investigation does not delete its repository** (archives are reused across
   investigations); remove repositories manually if required.
8. **Timing side channels, resource contention between concurrent sandboxes, and
   denial of service against the API itself** (beyond the queue cap) are not addressed.
