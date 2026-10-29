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
| M4 Sandbox runner | in progress: collector, result parsing and command builder done; Docker execution untested (Docker not installed on the dev machine) |
| M5 LLM layer, test generation, validation | not started |
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
  verification/               result models and classification rules
backend/tests/{unit,security,integration}/
sandbox-images/python/        sandbox image Dockerfile
```

## Known limitations

- Docker is not a complete security boundary. The sandbox hardening is documented in
  `docs/` once M8 lands; gVisor or a microVM is the recommended next layer.
- Database code has only been run against SQLite.
- SQLAlchemy is pinned to 2.0.x because 2.1 needs compiled modules that some Windows
  Application Control policies block.
- File ranking quality has only been checked on small synthetic repos.
