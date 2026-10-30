"""Real-Docker sandbox tests (marker: ``docker``).

These are the only tests that exercise the actual container sandbox. They are skipped when no
Docker daemon or sandbox image is available, unless REDFIRST_REQUIRE_DOCKER=1 is set (as in
.github/workflows/sandbox.yml), in which case unavailability is a failure, not a skip.

Build the image first:  docker build -t redfirst-sandbox-python:3.12 sandbox-images/python
Run:                    REDFIRST_REQUIRE_DOCKER=1 python -m pytest -m docker -rA

A passing run shows these specific abuses are contained by this configuration; it does not
prove the container cannot be escaped. NOTE: as of M9.1 these tests have never been run (no
Docker on the development machine); every assumption about container behaviour in them is
unverified until the CI workflow passes.

Each test is written so that it FAILS if the property it names regresses: the generated test
code itself asserts the property from inside the container (so a missing restriction makes the
test pass in the container, and the host-side assertion on the result then fails).
"""

import os
import subprocess
import textwrap

import pytest

from redfirst.domain.enums import Outcome, OutcomeReason, TestStatus
from redfirst.sandbox.executor import PLUGIN_DIR
from redfirst.sandbox.runner import docker_available, run_test_in_sandbox
from redfirst.verification.models import FailureSignature, TestContract
from redfirst.verification.rules import classify

IMAGE = "redfirst-sandbox-python:3.12"
REQUIRED = os.environ.get("REDFIRST_REQUIRE_DOCKER") == "1"


def _image_present() -> bool:
    if not docker_available():
        return False
    proc = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    return proc.returncode == 0


AVAILABLE = _image_present()
pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not AVAILABLE and not REQUIRED,
                       reason="docker or sandbox image unavailable (set REDFIRST_REQUIRE_DOCKER=1 "
                              "to make this a failure)"),
]


@pytest.fixture(autouse=True)
def _require_docker():
    if not AVAILABLE:
        pytest.fail(f"REDFIRST_REQUIRE_DOCKER=1 but docker or image {IMAGE} is unavailable",
                    pytrace=False)


@pytest.fixture
def repo(tmp_path):
    """A repository the container's unprivileged user could WRITE to if the mount allowed it.

    The tree is world-writable on purpose: otherwise a missing `:ro` would go unnoticed,
    because the container's uid has no write permission on host files it does not own.
    """
    r = tmp_path / "repo"
    (r / "app").mkdir(parents=True)
    (r / "app" / "__init__.py").write_text("")
    (r / "app" / "users.py").write_text('def register(d):\n    return d["username"]\n')
    for path in [r, r / "app", *(r / "app").iterdir()]:
        os.chmod(path, 0o777 if path.is_dir() else 0o666)
    return r


def run(repo, tmp_path, code, **kw):
    return run_test_in_sandbox(image=IMAGE, repo_dir=repo, test_code=textwrap.dedent(code),
                               plugin_dir=PLUGIN_DIR, work_dir=tmp_path / "work", **kw)


def container_gone(name: str) -> bool:
    proc = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^/{name}$",
                           "--format", "{{.Names}}"], capture_output=True, text=True, check=False)
    return proc.returncode == 0 and proc.stdout.strip() == ""


CONTRACT = TestContract(target_modules=["app/users.py"],
                        expected_signature=FailureSignature(exception_type="KeyError"),
                        exercises_target=True)


def assert_main_passed(out):
    """The property assertions run inside the container; success means the property holds."""
    assert out.result.integrity_errors == [], (out.result, out.stderr[-1500:])
    assert out.result.main_status is TestStatus.PASSED, (out.result.exception_type,
                                                         out.result.message, out.stdout[-1500:])
    assert out.container_removed and container_gone(out.container_name)


# -- ordinary runs ------------------------------------------------------------------------------
def test_failing_test_reproduces_with_repository_frames(repo, tmp_path):
    out = run(repo, tmp_path, """
        from app.users import register
        def test_reproduces_bug():
            register({})
        """)
    r = out.result
    assert out.exit_code == 1 and r.integrity_errors == [], (r, out.stderr[-2000:])
    assert r.main_status is TestStatus.FAILED and r.exception_type == "KeyError"
    assert [f.repo_path for f in r.frames if f.repo_path] == ["app/users.py"]
    assert r.frames[0].in_generated_test
    v = classify([r], CONTRACT)
    assert (v.outcome, v.reason) == (Outcome.REPRODUCED, OutcomeReason.MATCHING_FAILURE)
    assert out.container_removed and container_gone(out.container_name)
    assert "REDFIRST-REPORT" not in out.stdout  # the report block is not shown as output


def test_passing_test_is_not_reproduced_and_cleans_up(repo, tmp_path):
    out = run(repo, tmp_path, """
        from app.users import register
        def test_reproduces_bug():
            assert register({'username': 'a'}) == 'a'
        """)
    assert out.exit_code == 0 and out.result.integrity_errors == [], out.stderr[-2000:]
    assert classify([out.result], CONTRACT).outcome is Outcome.NOT_REPRODUCED
    assert out.container_removed and container_gone(out.container_name)


def test_repository_files_named_like_stdlib_modules_do_not_break_the_run(repo, tmp_path):
    (repo / "types.py").write_text("SHADOW = True\n")
    (repo / "re.py").write_text("SHADOW = True\n")
    os.chmod(repo / "types.py", 0o666)
    os.chmod(repo / "re.py", 0o666)
    out = run(repo, tmp_path, """
        import types, re
        from app.users import register
        def test_reproduces_bug():
            assert hasattr(types, 'ModuleType') and hasattr(re, 'compile')
            register({})
        """)
    assert out.result.integrity_errors == [], (out.result, out.stderr[-1500:])
    assert out.result.exception_type == "KeyError"


# -- resource limits ----------------------------------------------------------------------------
def test_infinite_loop_times_out_and_the_container_is_removed(repo, tmp_path):
    out = run(repo, tmp_path, "def test_reproduces_bug():\n    while True:\n        pass\n",
              timeout_seconds=5)
    assert out.result.timed_out
    assert classify([out.result], CONTRACT).reason is OutcomeReason.RESOURCE_LIMIT
    assert out.container_removed and container_gone(out.container_name)


def test_memory_exhaustion_is_reported_as_an_oom_kill(repo, tmp_path):
    out = run(repo, tmp_path, """
        def test_reproduces_bug():
            chunks = []
            while True:
                chunks.append(b'x' * (64 * 1024 * 1024))
        """, memory="256m")
    assert out.result.oom_killed, (out.exit_code, out.stderr[-2000:])
    assert classify([out.result], CONTRACT).reason is OutcomeReason.RESOURCE_LIMIT
    assert out.container_removed and container_gone(out.container_name)


def test_process_limit_stops_a_fork_bomb_quickly(repo, tmp_path):
    """Fails if --pids-limit is removed: fork() would keep succeeding until memory runs out."""
    out = run(repo, tmp_path, """
        import os, time
        def test_reproduces_bug():
            pids, error = [], None
            try:
                for _ in range(1000):
                    pid = os.fork()
                    if pid == 0:
                        time.sleep(60)
                        os._exit(0)
                    pids.append(pid)
            except OSError as exc:
                error = exc
            for pid in pids:
                os.kill(pid, 9)
            assert error is not None, 'fork never failed'
            assert len(pids) <= 128, f'{len(pids)} processes were allowed'
        """, timeout_seconds=30)
    assert_main_passed(out)


def test_report_area_is_a_small_tmpfs(repo, tmp_path):
    """Fails if /out becomes a host mount or loses its size limit."""
    out = run(repo, tmp_path, """
        import errno
        def test_reproduces_bug():
            mounts = open('/proc/mounts').read().splitlines()
            line = next(m for m in mounts if m.split()[1] == '/out')
            assert line.split()[0] == 'tmpfs' and 'noexec' in line, line
            total, failure = 0, None
            try:
                for i in range(8):
                    with open(f'/out/junk{i}', 'wb') as fh:
                        fh.write(b'x' * (1024 * 1024))
                    total += 1024 * 1024
            except OSError as exc:
                failure = exc
            assert failure is not None and failure.errno == errno.ENOSPC, failure
            assert total <= 2 * 1024 * 1024, total
        """)
    assert_main_passed(out)


# -- isolation ----------------------------------------------------------------------------------
def test_network_is_blocked(repo, tmp_path):
    """Fails if --network none is removed: the connection or the interface list would differ."""
    out = run(repo, tmp_path, """
        import os, socket
        def test_reproduces_bug():
            assert sorted(os.listdir('/sys/class/net')) == ['lo']
            failed = False
            try:
                socket.create_connection(('1.1.1.1', 53), timeout=3)
            except OSError:
                failed = True
            assert failed, 'outbound connection succeeded'
            try:
                socket.getaddrinfo('example.com', 80)
            except OSError:
                return
            raise AssertionError('DNS resolution worked')
        """)
    assert_main_passed(out)


def test_repository_mount_is_read_only(repo, tmp_path):
    """Fails if `:ro` is removed: the repository tree is world-writable (see the fixture)."""
    out = run(repo, tmp_path, """
        import errno
        def test_reproduces_bug():
            try:
                open('/repo/x.txt', 'w').write('x')
            except OSError as exc:
                assert exc.errno == errno.EROFS, exc
                return
            raise AssertionError('wrote into /repo')
        """)
    assert_main_passed(out)
    assert not (repo / "x.txt").exists()


def test_root_filesystem_is_read_only_and_tmp_is_noexec(repo, tmp_path):
    out = run(repo, tmp_path, """
        import errno
        def test_reproduces_bug():
            for path in ('/etc/redfirst', '/usr/redfirst', '/redfirst'):
                try:
                    open(path, 'w').write('x')
                except OSError as exc:
                    assert exc.errno in (errno.EROFS, errno.EACCES), (path, exc)
                else:
                    raise AssertionError(f'wrote {path}')
            mounts = {m.split()[1]: m for m in open('/proc/mounts').read().splitlines()}
            assert 'noexec' in mounts['/tmp'] and 'nosuid' in mounts['/tmp']
        """)
    assert_main_passed(out)


def test_process_is_unprivileged_with_no_capabilities(repo, tmp_path):
    out = run(repo, tmp_path, """
        import os
        def test_reproduces_bug():
            assert (os.getuid(), os.getgid()) == (10001, 10001)
            status = dict(line.split(':\\t', 1) for line in open('/proc/self/status')
                          if ':\\t' in line)
            for field in ('CapEff', 'CapPrm', 'CapBnd'):
                assert int(status[field].strip(), 16) == 0, (field, status[field])
            assert status['NoNewPrivs'].strip() == '1'
        """)
    assert_main_passed(out)


def test_worker_secrets_and_the_docker_socket_are_not_visible(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sentinel-not-a-real-key")
    monkeypatch.setenv("REDFIRST_LLM_API_KEY", "sentinel-not-a-real-key")
    out = run(repo, tmp_path, """
        import os
        def test_reproduces_bug():
            for name, value in os.environ.items():
                assert 'sentinel-not-a-real-key' not in value, name
            words = ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')
            suspicious = [n for n in os.environ if any(w in n.upper() for w in words)]
            assert suspicious == [], suspicious
            assert not os.path.exists('/var/run/docker.sock')
            assert not os.path.exists('/run/docker.sock')
        """)
    assert_main_passed(out)


# -- output handling ----------------------------------------------------------------------------
def test_huge_output_is_truncated(repo, tmp_path):
    # pytest prints the captured output of a *failing* test, so this produces ~5 MB of stdout.
    out = run(repo, tmp_path,
              "def test_reproduces_bug():\n    print('x' * 5_000_000)\n    assert False\n")
    assert out.output_truncated and len(out.stdout) <= 256 * 1024
    assert out.result.integrity_errors == []  # the report survived: it is printed last


def test_output_flood_is_stopped_and_reported_as_a_resource_limit(repo, tmp_path):
    """Writes straight to the container's real stdout (PID 1's fd), past pytest's capture."""
    out = run(repo, tmp_path, """
        def test_reproduces_bug():
            with open('/proc/1/fd/1', 'wb', buffering=0) as stream:
                while True:
                    stream.write(b'y' * 65536)
        """, timeout_seconds=120)
    assert out.result.output_flooded, (out.exit_code, out.stderr[-500:])
    assert classify([out.result], CONTRACT).reason is OutcomeReason.RESOURCE_LIMIT
    assert out.container_removed and container_gone(out.container_name)


# -- report integrity ---------------------------------------------------------------------------
def test_report_rewritten_by_repository_code_is_rejected(repo, tmp_path):
    (repo / "app" / "users.py").write_text(textwrap.dedent("""
        import atexit, json, os
        def _forge():
            ok = {'setup': {'outcome': 'passed'}, 'call': {'outcome': 'passed'},
                  'teardown': {'outcome': 'passed'}}
            with open(os.environ['REDFIRST_REPORT_PATH'], 'w') as fh:
                json.dump({'exitstatus': 0, 'collection_errors': [], 'tests': {
                    'test_redfirst.py::test_reproduces_bug': {'phases': ok}}}, fh)
        atexit.register(_forge)
        def register(d):
            return d['username']
        """))
    out = run(repo, tmp_path, """
        from app.users import register
        def test_reproduces_bug():
            register({})
        """)
    assert out.exit_code == 1
    v = classify([out.result], CONTRACT)
    assert (v.outcome, v.reason) == (Outcome.INCONCLUSIVE, OutcomeReason.INVALID_REPORT)


def test_a_process_left_running_cannot_print_a_forged_report_after_the_real_one(repo, tmp_path):
    """Fails if the wrapper stops killing other processes before it prints the report.

    The child reads the run's nonce from PID 1's command line (where an attacker can find it)
    and keeps printing a forged block to the container's real stdout. The final block must still
    be the collector's real report, so the verdict is the real REPRODUCED.
    """
    out = run(repo, tmp_path, """
        import os, re, time
        from app.users import register
        def test_reproduces_bug():
            cmdline = open('/proc/1/cmdline', 'rb').read().decode(errors='replace')
            nonce = re.search(r'REDFIRST-REPORT-BEGIN ([0-9a-f]{32})', cmdline).group(1)
            forged = ('\\n@@REDFIRST-REPORT-BEGIN %s@@\\n'
                      '{"exitstatus": 1, "collection_errors": [], "tests": {}}\\n'
                      '@@REDFIRST-REPORT-END %s@@\\n' % (nonce, nonce)).encode()
            if os.fork() == 0:
                with open('/proc/1/fd/1', 'wb', buffering=0) as stream:
                    while True:
                        stream.write(forged)
                        time.sleep(0.01)
            time.sleep(0.5)
            register({})
        """, timeout_seconds=60)
    assert out.result.integrity_errors == [], (out.result.integrity_errors, out.stdout[-500:])
    v = classify([out.result], CONTRACT)
    assert (v.outcome, v.reason) == (Outcome.REPRODUCED, OutcomeReason.MATCHING_FAILURE)


def test_stragglers_that_exhaust_the_process_limit_still_cannot_print_after_the_report(
        repo, tmp_path):
    """Fails if the wrapper's kill step needs a new process (M9.2, M1).

    The tests fill the container's process limit with children that keep printing a forged
    block. The wrapper used to start `python` to kill them; that fork failed, the error was
    silenced, and the children outlived it. The forged report claims exit status 77, so any
    integrity error mentioning 77 means a forged block was taken as the report.
    """
    out = run(repo, tmp_path, """
        import os, re, time
        from app.users import register
        def test_reproduces_bug():
            cmdline = open('/proc/1/cmdline', 'rb').read().decode(errors='replace')
            nonce = re.search(r'REDFIRST-REPORT-BEGIN ([0-9a-f]{32})', cmdline).group(1)
            forged = ('\\n@@REDFIRST-REPORT-BEGIN %s@@\\n'
                      '{"exitstatus": 77, "collection_errors": [], "tests": {}}\\n'
                      '@@REDFIRST-REPORT-END %s@@\\n' % (nonce, nonce)).encode()
            children = 0
            while True:
                try:
                    pid = os.fork()
                except OSError:
                    break  # the process limit is reached
                if pid == 0:
                    try:
                        with open('/proc/1/fd/1', 'wb', buffering=0) as stream:
                            while True:
                                stream.write(forged)
                                time.sleep(0.01)
                    finally:
                        os._exit(0)
                children += 1
            assert children > 50, children
            time.sleep(0.5)
            register({})
        """, timeout_seconds=60)
    assert not any("77" in e for e in out.result.integrity_errors), out.result.integrity_errors
    v = classify([out.result], CONTRACT)
    # Either the real report got through, or (if `cat` itself could not start) there is none;
    # a forged report must never be accepted.
    assert (v.outcome, v.reason) in {(Outcome.REPRODUCED, OutcomeReason.MATCHING_FAILURE),
                                     (Outcome.INCONCLUSIVE, OutcomeReason.INVALID_REPORT)}, v
    assert out.container_removed and container_gone(out.container_name)


def test_report_replaced_by_a_symlink_to_a_container_file_does_not_leak_into_output(repo,
                                                                                    tmp_path):
    out = run(repo, tmp_path, """
        import os
        def test_reproduces_bug():
            os.symlink('/etc/passwd', '/out/report.json')
        """)
    assert "root:x:0:0" not in out.stdout and "root:x:0:0" not in out.stderr
    assert classify([out.result], CONTRACT).outcome in (Outcome.INCONCLUSIVE,
                                                        Outcome.EXECUTION_ERROR)
    assert out.container_removed and container_gone(out.container_name)
