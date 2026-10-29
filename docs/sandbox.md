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

The worker (outside the container) enforces the wall-clock timeout, force-removes the
container afterwards, truncates captured output to 256 KB per stream, and treats a missing
report as "no usable result" rather than guessing.

**Status: the command's flags are unit-tested as strings. The container has never been run**
because no Docker daemon was available on the development machine. Run the abuse tests before
trusting any of the above:

```bash
docker build -t redfirst-sandbox-python:3.12 sandbox-images/python
cd backend
uv run python -m pytest tests/integration/test_sandbox_docker.py -rs
```

They cover an infinite loop, a network connection attempt, a write to the read-only repo, a
fork bomb, a memory blow-up and 5 MB of output. A passing run shows these specific abuses are
contained; it does not prove the container cannot be escaped.

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
