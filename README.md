# REDFIRST

Automated bug reproduction and verification for Python projects. Given a bug report and a
repository, REDFIRST generates a pytest reproduction test, runs it in an isolated sandbox, and
classifies the result from structured execution evidence. The LLM writes the test; it never
decides the verdict.

**Outcomes:** `REPRODUCED`, `NOT_REPRODUCED`, `INCONCLUSIVE`, `EXECUTION_ERROR`.
A failing test is not automatically a reproduction (see `backend/redfirst/verification/rules.py`).

## Status

Early development. Backend and web UI work end to end with a scripted model; the Docker
sandbox and the live Claude API have not been exercised yet (see Known limitations).

| Milestone | State |
|---|---|
| M0 Skeleton (FastAPI `/health`, settings) | done |
| M1 Domain model, state machine, deterministic verifier | done |
| M2 Safe archive extraction, layout detection | done |
| M3 Repository analysis (AST index, tracebacks, search, ranking) | done |
| Persistence (SQLAlchemy models, Alembic migration) | done (tested on SQLite only) |
| M4 Sandbox runner | code written; collector, result parsing and `docker run` flags tested. Real Docker execution **not yet verified** (Docker not installed on the dev machine) |
| M5 LLM layer, test generation, validation | done with mocked model responses; **never run against the live API** (no key on the dev machine) |
| M6 Orchestrator, worker, API, export | done; end-to-end tested on 6 fixture repos with scripted model output and local (unsandboxed) pytest execution |
| M7 Frontend (Next.js) | done; unit-tested, production build passes, and checked in a browser against a running API (live SSE updates, desktop and phone width, light and dark) |
| M8 Hardening and docs | done for what can be tested without Docker or a live model: LLM budgets, input and queue caps, secret redaction, retention, threat model, sandbox notes. The sandbox itself is still unverified |
| M9 Correctness and verdict integrity | done: canonical target matching, untrusted-report checks, stricter validator, conditional state transitions, worker leases, container lifecycle (OOM detection), async SSE, archive limits, LLM accounting, pagination bounds, retention order, and a CI workflow for Docker. **Docker tests have still never run** (no Docker locally; CI not yet run) |
| M9.1 Review fixes (R1-R8) | done: assertions must depend on target results, validator bypasses closed, Host-header validation, SQLite-safe migrations, stdlib-shadowing fix, bounded output and no writable host mount for the sandbox, stronger Docker tests (17). **Still no Docker or PostgreSQL run** |
| M9.2 Final-review fixes | done: web UI listens on 127.0.0.1 only; wrong-value evidence needs a direct check of the result (`assert r != r` no longer counts); the sandbox wrapper kills leftover processes with a builtin that works at the process limit; prompt v4. Docker behaviour still unverified |
| M10 Verdict-first investigation page | done: the verdict is a banner with its reason, a caveat and key facts; evidence is shown by meaning with repository-relative paths; stage stepper, export menu, next steps beside the verdict; fixes dates that were off by the viewer's UTC offset. Checked live against all eight states, light and dark, desktop and phone width |
| M11 Brand and dashboard | done: logo mark and warm neutral palette (red reserved for the mark and for confirmed bugs and errors), Light/System/Dark toggle, dashboard with outcome breakdown, 14-day activity, needs-attention list and first-run steps, `?result=` filter links, page transitions that respect reduced motion. Status colours checked at 4.5:1 contrast or better in both themes; 12 pages checked for overflow at 375 and 1280 px in both themes |
| M12 New-investigation flow | done: Code / The bug / More detail layout with a live "What REDFIRST will use" panel (real consequences, no score), examples, counters and limits mirrored from the backend (a test fails on drift), drag-and-drop upload with browser-side checks, project creation on the page, a "Try a sample bug" button, saved drafts, Ctrl/Cmd+Enter. Run end to end against a fresh empty API: sample, Start, queued investigation; the worker was not running, so no investigation was executed |
| M13 Navigation and accessibility | done: phone navigation that was unusable (57 px slot) is now two rows, skip link, breadcrumbs, real page titles, a confirmation before Cancel (focus trapped, Escape closes), screen reader announcements that no longer tick every second, 24 px+ targets with whole-row links, searchable/sortable list whose filters live in the URL, and an axe-core test over every page state. Not tested with a real screen reader (none available here) |

## Quick start (Windows)

From the repository root in PowerShell:

```powershell
.\dev.ps1
```

It creates `backend\.env` from `.env.example` if there is none (SQLite, no secrets), installs
missing dependencies, applies database migrations, and opens the API, the worker and the web UI
in their own windows, then the browser at http://localhost:3000. Close a window to stop that
service. Use `-NoWorker` while Docker is not set up. If PowerShell refuses to run scripts:
`powershell -ExecutionPolicy Bypass -File .\dev.ps1`.

Windows PowerShell 5.1 does not understand `&&` or `VAR=value command`; run commands on
separate lines, and set variables with `$env:NAME = "value"`.

## Running a real investigation

A real investigation needs two things this repository cannot provide:

1. **Docker**, for the sandbox. On Windows, Docker Desktop needs WSL 2:
   `winget install --id Microsoft.WSL --exact`, then
   `dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart`
   (both in an administrator PowerShell), restart, then
   `winget install --id Docker.DockerDesktop --exact`. Start Docker Desktop, then build the
   sandbox image from the repository root:
   `docker build -t redfirst-sandbox-python:3.12 sandbox-images/python`
2. **An Anthropic API key**, from https://console.anthropic.com. Put it after
   `REDFIRST_LLM_API_KEY=` in `backend/.env` (git-ignored). Never commit it or paste it into a chat.

The worker checks both when it starts: without Docker or the sandbox image it says what is missing
and exits without claiming anything, so investigations stay queued; a missing key is a warning.
`backend/.env` caps model usage (`REDFIRST_LLM_TOKEN_BUDGET_PER_INVESTIGATION`,
`REDFIRST_LLM_MAX_CALLS_PER_DAY`).

## Setup (Windows / macOS / Linux)

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 20.9+ and pnpm for the web
UI. Docker is required only for sandbox execution and PostgreSQL via `docker-compose.yml`.

```bash
cd backend
uv sync
uv run python -m pytest        # use `python -m pytest`; some Windows policies block pytest.exe
uv run ruff check .
```

Tests marked `docker` are the only ones that use the real container sandbox; they are skipped
when Docker or the sandbox image is missing. To run them (set `REDFIRST_REQUIRE_DOCKER=1` to make
a missing Docker a failure instead of a skip):

```bash
docker build -t redfirst-sandbox-python:3.12 sandbox-images/python
cd backend
REDFIRST_REQUIRE_DOCKER=1 uv run python -m pytest -m docker -rA
```

In PowerShell, set the variable first: `$env:REDFIRST_REQUIRE_DOCKER = "1"`, then run the pytest line.

CI: `.github/workflows/sandbox.yml` runs the non-Docker suite and the Docker suite on GitHub's
Linux runners (read-only token, no secrets, actions pinned by SHA).

Copy `.env.example` to `backend/.env` and adjust (it defaults to SQLite, so no database server is
needed). Never commit real secrets.

Apply database migrations (needs a database; see `REDFIRST_DATABASE_URL`). Existing databases
must be upgraded before running M9 code: migration `0002` adds the worker lease columns.

```bash
uv run python -m alembic upgrade head
```

Run the API (binds to 127.0.0.1; there is **no authentication** yet) and, separately, the worker:

```bash
uv run python -m uvicorn redfirst.api.app:create_app --factory --host 127.0.0.1 --port 8000
uv run python -m redfirst.worker      # needs Docker + the sandbox image, and an Anthropic key
```

Run the web UI (proxies `/api/*` to the backend; see `frontend/README.md`):

```bash
cd frontend
pnpm install
pnpm dev                               # http://localhost:3000
```

The UI has a dashboard, investigation history with filters, projects with archive upload, a
new-investigation form, and an investigation workspace with live stage progress, the outcome,
evidence, the generated test, per-run logs, the bug report, a timeline and exports.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/projects` | Create a project |
| GET | `/api/projects` | List projects |
| POST | `/api/projects/{id}/repositories` | Upload a zip/tar.gz (multipart field `archive`); validated by a safe extraction |
| GET | `/api/projects/{id}/repositories` | List repositories |
| POST | `/api/projects/{id}/investigations` | Create an investigation from a bug report |
| GET | `/api/investigations` | History (optional `project_id`; `limit` 1-200, default 50; out of range is 422) |
| GET | `/api/investigations/{id}` | Full evidence report |
| GET | `/api/investigations/{id}/events` | Live progress (Server-Sent Events; honours `Last-Event-ID`) |
| POST | `/api/investigations/{id}/cancel` | Cancel a running investigation |
| GET | `/api/investigations/{id}/export/test` | Download the executed test |
| GET | `/api/investigations/{id}/export/report?format=json\|md` | Download the report |
| DELETE | `/api/investigations/{id}` | Delete a finished investigation and its stored logs (409 if still running) |

The API never runs repository code. The worker claims `CREATED` investigations from the
database (no message broker), drives them through the state machine and commits at every
stage, so partial investigations remain inspectable.

### Workers and concurrency

- Several workers may run at once. A claim is a compare-and-swap from `CREATED` that records
  the worker id and a lease (`REDFIRST_WORKER_LEASE_SECONDS`, default 120). A heartbeat thread
  renews the lease every quarter of that while the worker runs.
- Every worker loop iteration fails runs whose lease has expired (`FAILED`, `WorkerLost`,
  retryable). Starting a worker never touches runs a live worker is heartbeating. Runs are not
  resumed. Lease expiry uses worker clocks, so keep worker hosts NTP-synchronised; the lease must
  comfortably exceed clock skew.
- State changes are compare-and-swap updates: a worker acting on a stale read (for example after
  a user cancelled) gets a conflict and stops instead of overwriting the newer state.
- **SQLite** serialises writers; the compare-and-swap claim and transitions are tested there,
  including a multi-threaded claim race. Use SQLite for a single host only.
- **PostgreSQL** additionally uses `FOR UPDATE SKIP LOCKED` so workers skip rows another worker is
  claiming. The same compare-and-swap guarantees apply, but **PostgreSQL has not been tested**.

## Layout

```
backend/redfirst/
  api/ core/ db/ domain/      application, config, persistence, enums and state machine
  repos/                      safe archive extraction, layout detection
  analysis/                   AST index, traceback parsing, search, ranking
  sandbox/                    pytest collector, result parsing, docker runner
  llm/                        provider interface, Anthropic adapter, fake provider, prompt loader
  generation/                 evidence assembly, bounded generate -> validate -> repair loop
  validation/                 static policy checks on generated tests
  verification/               classification rules, evidence report
  storage/                    content-addressed blob store (archives, logs)
  worker/                     job queue, orchestrator, worker entry point
  security/                   secret redaction
docs/                         threat model, sandbox notes, verification rules
backend/prompts/              versioned prompt templates (name.version.md)
backend/tests/{unit,security,integration}/
frontend/                     Next.js web UI (see frontend/README.md)
fixtures/repos/               small repos with planted bugs for end-to-end tests
sandbox-images/python/        sandbox image Dockerfile
```

## Security and retention

- **Abuse controls** (all configurable, see `.env.example`): bug-report field size caps, a token
  budget per investigation, a rolling 24-hour cap on LLM calls, and a cap on unfinished
  investigations (the API answers 429). An exhausted budget ends the investigation as
  `FAILED` / `EXECUTION_ERROR` with `LLMBudgetExceeded` (retryable).
- **Host header validation:** the API and the web UI only answer requests whose Host is in
  `REDFIRST_ALLOWED_HOSTS` (default `localhost`, `127.0.0.1`; port ignored). The UI needs its
  own check (`frontend/src/proxy.ts`) because its `/api/*` proxy rewrites the Host header, so
  the API alone would never see what the browser sent (verified on a running stack). This
  stops DNS-rebinding reads from a browser. It does not stop plain cross-site requests, and it
  is not authentication: any client that can reach the port can send `Host: localhost`. That is
  why both servers listen on loopback only (`uvicorn --host 127.0.0.1`, and `pnpm dev` /
  `pnpm start` pass `--hostname 127.0.0.1`; Next.js would otherwise listen on every interface,
  exposing the unauthenticated API, code execution and the LLM budget to the local network).
  Set the same variable in `frontend/.env.local` if you add hosts, and only together with real
  authentication.
- **Untrusted test reports:** the pytest report is written inside the test process, so REDFIRST
  treats it as untrusted input: strict schema, size limit, no symlinks, and a cross-check against
  the exit code and OOM state read from the container runtime. Any contradiction ends the
  attempt as `INCONCLUSIVE` / `invalid_report`. Code that controls both the report and its own
  exit status can still forge a consistent result; see the threat model.
- **Redaction:** common credential formats are removed from stored sandbox output, verdict
  evidence and model feedback, and from repository text before it is sent to the model.
- **Retention:** finished investigations older than `REDFIRST_RETENTION_DAYS` (default 30) are
  deleted by `uv run python -m redfirst.db.retention`; run it from cron or a scheduler.
  Repositories are kept.

Documentation: [threat model](docs/threat-model.md) (every threat, its control and how it was
verified), [sandbox notes and gVisor/microVM options](docs/sandbox.md), and
[how the outcome is decided](docs/verification-rules.md).

## LLM configuration

The model is used through a provider-neutral interface (`redfirst/llm/base.py`); only
Anthropic is implemented. Defaults: `claude-opus-5-5`, effort `high`, structured outputs via
the official SDK, and **server-side refusal fallbacks enabled** (`REDFIRST_LLM_REFUSAL_FALLBACKS`;
set to `false` to turn off). The API key comes from `REDFIRST_LLM_API_KEY`, or the SDK's own
`ANTHROPIC_API_KEY` / profile resolution when unset. Every attempt, including failed ones,
records the provider, configured and served model, prompt name and version, a call status
(`succeeded`, `invalid_output`, `refused`, `provider_error`, or `not_sent` when REDFIRST's own
budget blocked the call), and token usage and request id when the provider reported them.
Unknown usage is recorded as unknown, never estimated. The worker uses prompt `generate_test.v2`.

The model never sets the verdict. Generated tests are validated statically
(`validation/policy.py`), run in the sandbox, and classified by `verification/rules.py`.

## Known limitations

- Docker is not a complete security boundary; see `docs/sandbox.md` for gVisor and microVM
  options (recommendations only, none tried here).
- There is **no authentication**: anyone who can reach the API can read investigations and spend
  LLM budget. Keep it on localhost. See `docs/threat-model.md` for all residual risks.
- Redaction only recognises common secret formats.
- The Docker sandbox runner (`sandbox/runner.py`) and its 18 Docker tests (success, failure,
  timeout, OOM, process limit, report tmpfs, network, read-only mounts, privileges, secrets,
  output, tampering) have **never
  been run**: no Docker on the dev machine, and the CI workflow has not run yet. The runner's
  control flow is unit-tested against a fake docker CLI only.
- A verdict on an untrusted repository can be forged by repository code that rewrites the test
  report so it matches the exit status the run really had. The attacker does not need to
  control the exit code: a genuine unrelated failure already exits 1. Detection covers
  contradictions only (two strict-xfail tests document the gap); see `docs/threat-model.md`.
- The generated test runs from a separate directory, so the repository's own `conftest.py` is
  not applied yet.
- The Anthropic adapter is tested against a stubbed SDK client only; no real API call has been
  made. Generation quality on real bugs is unmeasured.
- The static validator is a hygiene gate, not a security boundary; it can be evaded (for
  example through modules the repository itself imports). It is also strict: tests that need file
  access, `os`, `sys`, `getattr` or private attributes of non-repository objects are rejected.
- End-to-end tests use a scripted model and run fixture tests with plain local pytest, not the
  Docker sandbox. They prove the pipeline and verdict logic, not isolation or model quality.
- The API and web UI have no authentication and are meant for single-user local use only.
- The browser check of the UI used investigations completed by the real orchestrator with a
  scripted model and unsandboxed local pytest, not a real worker.
- Frontend types are hand-written mirrors of the backend schemas, not generated from OpenAPI.
- Wrong-return-value bugs are classified REPRODUCED when a predicted `AssertionError` is raised
  in the main test that calls target code and the control test passes. This is weaker evidence
  than a failure inside target code, and the report says which kind it was.
- Repositories that need packages beyond pytest cannot be exercised (no dependency install).
- Database code has only been run against SQLite. PostgreSQL, including concurrent workers on
  PostgreSQL, is untested.
- SQLAlchemy is pinned to 2.0.x because 2.1 needs compiled modules that some Windows
  Application Control policies block.
- File ranking quality has only been checked on small synthetic repos.
