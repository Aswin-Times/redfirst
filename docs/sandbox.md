# Sandbox: what exists and what to add

## What exists today

`backend/redfirst/sandbox/docker_cmd.py` builds one `docker run` command per test run:

| Control | Flag |
|---|---|
| No network | `--network none` |
| Immutable root filesystem | `--read-only`, plus `--tmpfs /tmp:rw,noexec,nosuid,size=64m` |
| Unprivileged user | `--user 10001:10001` |
| No capabilities, no privilege gain | `--cap-drop ALL`, `--security-opt no-new-privileges` |
| Memory, swap, CPU, processes | `--memory 512m --memory-swap 512m --cpus 1 --pids-limit 128` |
| File and descriptor limits | `--ulimit nofile=256:256 --ulimit fsize=10000000` |
| Repository read-only | `-v <repo>:/repo:ro` (generated test and collector also `:ro`) |
| One writable mount | `-v <out>:/out:rw`, receives only the JSON report |
| No secrets, no Docker socket | environment holds only `PYTHONPATH`, the report path and `PYTHONDONTWRITEBYTECODE` |

### Container lifecycle (`sandbox/runner.py`)

1. The run directory is created private to the worker (`0700`); inside it the generated-test
   directory is `0755` and the output directory `0777`, because the container's uid does not own
   host directories. Inside the container only the bind-mounted directories themselves are
   visible, never their host parents. The worker's umask must let other users read the
   extracted repository (the default `022` does).
2. `docker run` starts the container **without `--rm`**, with the wall-clock timeout enforced by
   the worker. On timeout the container is killed and waited for.
3. The runner reads the container's state from Docker (`docker inspect`): exit code, `OOMKilled`,
   and whether it ever started. A container that never started is a runner failure carrying
   Docker's own error message.
4. The container is removed (`docker rm --force --volumes`) in a `finally` block on every path.
5. Captured output is truncated to 256 KB per stream.

### The test report is untrusted

The report is written by a pytest plugin in the same process as the code under test, which can
rewrite it. The runner reads it as untrusted input (strict schema, 1 MB limit, symlinks refused)
and cross-checks it against the exit code and OOM flag from step 3. A contradiction, or a
missing or malformed report, makes the attempt `INCONCLUSIVE` / `invalid_report`. This catches
corruption and naive tampering; it cannot stop code that also controls its own exit status
(see `docs/threat-model.md`, row 9a).

### Verification status

**The container has never been run**: no Docker daemon was available on the development
machine. The flags are tested as strings and the lifecycle is tested against a fake docker CLI;
neither proves runtime behaviour. Run the Docker tests before trusting any of the above:

```bash
docker build -t redfirst-sandbox-python:3.12 sandbox-images/python
cd backend
REDFIRST_REQUIRE_DOCKER=1 uv run python -m pytest -m docker -rA
```

They cover a passing and a failing test (including repository-relative frame mapping), an
infinite loop, an OOM kill, a network connection attempt, a write to the read-only repo, a fork
bomb, 5 MB of output, a repository that rewrites the report, and container cleanup after each.

`.github/workflows/sandbox.yml` runs the same tests on GitHub's Linux runners with
`REDFIRST_REQUIRE_DOCKER=1` (so a missing Docker fails the job instead of skipping), lists every
test that ran in the job summary, and uploads the JUnit results. It uses a read-only token, no
secrets and SHA-pinned official actions. **It has not run yet.** A passing run shows these
specific abuses are contained; it does not prove the container cannot be escaped.

## Why Docker alone is not enough

Containers share the host kernel. A hostile repository that finds a kernel or container-runtime
bug can reach the host, and the worker holds Docker access, so a successful escape reaches
the worker's secrets (the LLM key) and the database. The flags above reduce the attack surface;
they do not remove the kernel from the trust boundary.

## Stronger isolation options (recommendations, none tried here)

| Option | Idea | Trade-offs |
|---|---|---|
| **gVisor (`runsc`)** | An application kernel written in a memory-safe language intercepts syscalls, so the host kernel sees far fewer of them. Used as a Docker runtime: `docker run --runtime=runsc ...`. | Linux hosts only (not native Windows or macOS); some syscalls and features are unsupported; I/O and syscall-heavy tests run slower. The first thing to try, since it is mostly a runtime switch. |
| **Firecracker / Kata (microVM)** | Each run gets its own lightweight VM and kernel. | Strongest of the three; needs KVM (bare metal or nested virtualisation) and more operational work. |
| **Separate disposable host** | Run the worker and sandbox on a throwaway machine or VM with no secrets except a scoped LLM key. | Limits blast radius whatever the runtime; simple to reason about. |

Suggested order for a shared deployment: put the worker on its own VM with only a
spend-limited LLM key, then add gVisor, then consider microVMs if the threat model demands it.

None of these have been tested with REDFIRST. gVisor in particular is untested against the
pytest plugin and the read-only mounts used here.

## Other hardening worth doing before any shared use

- Authentication on the API (see `docs/threat-model.md`, residual risk 1).
- A seccomp profile tighter than Docker's default.
- Run the sandbox image from a pinned digest and rebuild it regularly.
- Cap concurrent sandboxes per host.
- Alert on `WorkerLost`, `LLMBudgetExceeded` and repeated `EXECUTION_ERROR` outcomes.
