# Sandbox: what exists and what to add

## What exists today

`backend/redfirst/sandbox/docker_cmd.py` builds one `docker run` command per test run:

| Control | Flag |
|---|---|
| No network | `--network none` |
| Immutable root filesystem, small tmpfs areas | `--read-only`, plus `--tmpfs /tmp:rw,noexec,nosuid,size=64m` and `--tmpfs /out:rw,noexec,nosuid,size=2m,mode=1777` |
| Unprivileged user | `--user 10001:10001` |
| No capabilities, no privilege gain | `--cap-drop ALL`, `--security-opt no-new-privileges` |
| Memory, swap, CPU, processes | `--memory 512m --memory-swap 512m --cpus 1 --pids-limit 128` |
| File, descriptor and log limits | `--ulimit nofile=256:256 --ulimit fsize=10000000`, `--log-driver json-file --log-opt max-size=1m --log-opt max-file=1` |
| Repository read-only | `-v <repo>:/repo:ro` (generated test and collector also `:ro`) |
| No writable host mount | the repository, generated test and collector plugin are bind-mounted `:ro`; the only writable places are the two tmpfs above, inside the container |
| No secrets, no Docker socket | environment holds only `PYTHONPATH` (the collector), `REDFIRST_SOURCE_ROOTS`, the report path and `PYTHONDONTWRITEBYTECODE` |

### Container lifecycle (`sandbox/runner.py`)

1. The run directory is created private to the worker (`0700`) and holds only the generated
   test (`gen/`, `0755`). **Nothing the container writes ever reaches the host**: every host
   directory is mounted read-only, and `/out` and `/tmp` are size-capped tmpfs inside the
   container. (Until M9.1 the report directory was a writable host bind mount, which was
   unbounded; it also needed `0777` permissions.) The worker's umask must still let other
   users read the extracted repository (the default `022` does).
2. `docker run` starts the container **without `--rm`**. PID 1 is a small `sh` wrapper that runs
   `python -P -m pytest ...`, keeps its exit status, kills every other process in the container,
   prints `/out/report.json` between two markers carrying a random per-run nonce, and exits with
   pytest's status.
3. The worker enforces the wall-clock timeout and reads the container's stdout/stderr through
   **bounded buffers** (first 192 KB and last 512 KB per stream, nothing more in memory). A run
   that prints more than 64 MB is stopped and reported as a resource limit. Docker's own log
   file is capped at 1 MB. Killing the docker CLI does not stop a container, so the runner also
   runs `docker kill`.
4. The runner reads the container's state from Docker (`docker inspect`): exit code, `OOMKilled`,
   and whether it ever started. A container that never started is a runner failure carrying
   Docker's own error message.
5. The container is removed (`docker rm --force --volumes`) in a `finally` block on every path.
6. The report block is removed from the output shown to users; stored output is truncated to
   256 KB per stream.

### Python path

Repository roots are **not** on `PYTHONPATH`, which precedes the standard library: a repository
file named `types.py` or `re.py` would otherwise replace the module pytest itself imports. The
collector plugin appends the roots to `sys.path` after the stdlib and site-packages, and
`python -P` keeps the working directory off the path.

### The test report is untrusted

The report is written by a pytest plugin in the same process as the code under test, which can
rewrite it. It travels to the host as text between the nonce markers (the last block carrying
the nonce wins), is parsed with a strict schema and a 256 KB limit, and is cross-checked against
the exit code and OOM flag from step 4. A contradiction, or a missing or malformed report, makes
the attempt `INCONCLUSIVE` / `invalid_report`. This catches corruption and tampering that
contradicts the real exit status. It does **not** stop a repository from rewriting the report to
agree with the exit status the run really had (for example "failed in target code" after a
genuine unrelated failure, exit 1): see `docs/threat-model.md`, row 9a and residual risk 3a.
The wrapper killing other processes before it prints stops a left-over child from printing a
forged block after the real one. The nonce does **not** do this: any process in the container
can read it from `/proc/1/cmdline`. The kill uses the shell's builtin `kill -9 -1` (sent twice),
which needs no new process, so it still works when the tests have used up the process limit;
until M9.2 it started `python` for this, and when that fork failed the error was silenced and
the children survived. Both cases are covered by Docker tests that have not yet run.

### Verification status

**The container has never been run**: no Docker daemon was available on the development
machine. The flags are tested as strings and the lifecycle is tested against a fake docker CLI;
neither proves runtime behaviour. Run the Docker tests before trusting any of the above:

```bash
docker build -t redfirst-sandbox-python:3.12 sandbox-images/python
cd backend
REDFIRST_REQUIRE_DOCKER=1 uv run python -m pytest -m docker -rA
```

The 18 tests each assert their property from inside the container, so that they fail if it
regresses: a passing and a failing test (with repository-relative frames), stdlib-named
repository files, an infinite loop, an OOM kill, the process limit, the size-capped report
area, network isolation (interface list, connect, DNS), the read-only repository (the test
tree is world-writable so only the mount can stop a write), the read-only root and noexec
tmpfs, non-root user with no capabilities, no worker secrets or Docker socket, 5 MB of
output, an output flood, a rewritten report, a left-over process printing a forged block
after the real one, and a report symlinked to a container file. **None has ever run.**

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
