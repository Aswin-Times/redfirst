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

## Setup (Windows / macOS / Linux)

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 20.9+ and pnpm for the web
UI. Docker is required only for sandbox execution and PostgreSQL via `docker-compose.yml`.

```bash
cd backend
uv sync
uv run python -m pytest        # use `python -m pytest`; some Windows policies block pytest.exe
uv run ruff check .
```

Copy `.env.example` to `backend/.env` and adjust. Never commit real secrets.

Apply database migrations (needs a database; see `REDFIRST_DATABASE_URL`):

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
| GET | `/api/investigations` | History (optional `project_id`) |
| GET | `/api/investigations/{id}` | Full evidence report |
| GET | `/api/investigations/{id}/events` | Live progress (Server-Sent Events; honours `Last-Event-ID`) |
| POST | `/api/investigations/{id}/cancel` | Cancel a running investigation |
| GET | `/api/investigations/{id}/export/test` | Download the executed test |
| GET | `/api/investigations/{id}/export/report?format=json\|md` | Download the report |
| DELETE | `/api/investigations/{id}` | Delete a finished investigation and its stored logs (409 if still running) |

The API never runs repository code. The worker claims `CREATED` investigations from the
database (no message broker), drives them through the state machine and commits at every
stage, so partial investigations remain inspectable. On start-up it marks investigations left
mid-pipeline by a dead worker as `FAILED` (`WorkerLost`); it does not resume them.

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
`ANTHROPIC_API_KEY` / profile resolution when unset. Every attempt records the model, prompt
name and version, token usage and request id.

The model never sets the verdict. Generated tests are validated statically
(`validation/policy.py`), run in the sandbox, and classified by `verification/rules.py`.

## Known limitations

- Docker is not a complete security boundary; see `docs/sandbox.md` for gVisor and microVM
  options (recommendations only, none tried here).
- There is **no authentication**: anyone who can reach the API can read investigations and spend
  LLM budget. Keep it on localhost. See `docs/threat-model.md` for all residual risks.
- Redaction only recognises common secret formats.
- The Docker sandbox runner (`sandbox/runner.py`) and its 7 abuse tests (infinite loop, network,
  read-only repo, fork bomb, memory, huge output) have **never been run**: no Docker on the dev
  machine. The collector and result parsing are tested with a plain local pytest subprocess only.
  To run them: install Docker, `docker build -t redfirst-sandbox-python:3.12 sandbox-images/python`,
  then `uv run python -m pytest tests/integration/test_sandbox_docker.py`.
- The generated test runs from a separate directory, so the repository's own `conftest.py` is
  not applied yet.
- The Anthropic adapter is tested against a stubbed SDK client only; no real API call has been
  made. Generation quality on real bugs is unmeasured.
- The static validator is a hygiene gate, not a security boundary; it can be evaded. It is also
  strict: tests that need file access, `os` or `sys` are rejected for now.
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
- Database code has only been run against SQLite; multi-worker claiming relies on PostgreSQL's
  `SKIP LOCKED` and is untested.
- SQLAlchemy is pinned to 2.0.x because 2.1 needs compiled modules that some Windows
  Application Control policies block.
- File ranking quality has only been checked on small synthetic repos.
