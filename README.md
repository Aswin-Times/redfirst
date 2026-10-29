# REDFIRST

Automated bug reproduction and verification for Python projects. Given a bug report and a
repository, REDFIRST generates a pytest reproduction test, runs it in an isolated sandbox, and
classifies the result from structured execution evidence. The LLM writes the test; it never
decides the verdict.

**Outcomes:** `REPRODUCED`, `NOT_REPRODUCED`, `INCONCLUSIVE`, `EXECUTION_ERROR`.
A failing test is not automatically a reproduction (see `backend/redfirst/verification/rules.py`).

## Status

Early development. Backend only; no frontend yet.

| Milestone | State |
|---|---|
| M0 Skeleton (FastAPI `/health`, settings) | done |
| M1 Domain model, state machine, deterministic verifier | done |
| M2 Safe archive extraction, layout detection | done |
| M3 Repository analysis (AST index, tracebacks, search, ranking) | done |
| Persistence (SQLAlchemy models, Alembic migration) | done (tested on SQLite only) |
| M4 Sandbox runner | code written; collector, result parsing and `docker run` flags tested. Real Docker execution **not yet verified** (Docker not installed on the dev machine) |
| M5 LLM layer, test generation, validation | done with mocked model responses; **never run against the live API** (no key on the dev machine) |
| M6 Orchestrator, worker, API, export | not started |
| M7 Frontend (Next.js) | not started |
| M8 Hardening and docs | not started |

## Setup (Windows / macOS / Linux)

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/). Docker is required only for sandbox
execution and PostgreSQL via `docker-compose.yml`.

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
backend/prompts/              versioned prompt templates (name.version.md)
  verification/               result models and classification rules
backend/tests/{unit,security,integration}/
sandbox-images/python/        sandbox image Dockerfile
```

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

- Docker is not a complete security boundary. The sandbox hardening is documented in
  `docs/` once M8 lands; gVisor or a microVM is the recommended next layer.
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
- Database code has only been run against SQLite.
- SQLAlchemy is pinned to 2.0.x because 2.1 needs compiled modules that some Windows
  Application Control policies block.
- File ranking quality has only been checked on small synthetic repos.
