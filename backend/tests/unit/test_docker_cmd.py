import re
from pathlib import Path

from redfirst.sandbox.docker_cmd import SandboxSpec, build_docker_args
from redfirst.sandbox.results import REPORT_BEGIN, REPORT_END

NONCE = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def args(**kw):
    spec = SandboxSpec(image="img", name="c1", repo_dir=Path("/r"), gen_dir=Path("/g"),
                       plugin_dir=Path("/p"), nonce=NONCE, **kw)
    return build_docker_args(spec)


def pairs(a):
    return {a[i]: a[i + 1] for i in range(len(a) - 1) if a[i].startswith("--")}


def test_isolation_flags_present():
    a = args()
    p = pairs(a)
    assert p["--network"] == "none"
    assert "--read-only" in a
    assert p["--cap-drop"] == "ALL"
    assert p["--security-opt"] == "no-new-privileges"
    assert p["--user"] == "10001:10001"
    assert p["--pids-limit"] == "128"
    assert p["--memory"] == p["--memory-swap"] == "512m"
    assert "noexec" in p["--tmpfs"]


def mounts(a):
    return [a[i + 1] for i, x in enumerate(a) if x == "-v"]


def test_no_host_directory_is_writable_by_the_container():
    """M9.1 R3: a writable host bind mount is unbounded (one 10 MB file at a time, forever)."""
    m = mounts(args())
    assert len(m) == 3 and all(x.endswith(":ro") for x in m), m
    assert not any(":/out" in x for x in m)


def test_report_area_is_a_small_tmpfs_inside_the_container():
    a = args()
    tmpfs = [a[i + 1] for i, x in enumerate(a) if x == "--tmpfs"]
    out = next(t for t in tmpfs if t.startswith("/out:"))
    size = re.search(r"size=(\d+)m", out)
    assert size and int(size.group(1)) <= 4, out
    assert "noexec" in out and "nosuid" in out
    assert "REDFIRST_REPORT_PATH=/out/report.json" in a


def test_docker_log_file_is_capped():
    p = pairs(args())
    assert p["--log-driver"] == "json-file"
    opts = [args()[i + 1] for i, x in enumerate(args()) if x == "--log-opt"]
    assert "max-size=1m" in opts and "max-file=1" in opts


def test_report_is_printed_by_a_wrapper_after_pytest_exits_between_nonce_markers():
    a = args()
    i = a.index("sh")
    assert a[i + 1] == "-c"
    script = a[i + 2]
    assert REPORT_BEGIN.format(nonce=NONCE) in script and REPORT_END.format(nonce=NONCE) in script
    assert "cat /out/report.json" in script and script.rstrip().endswith('exit "$status"')
    # pytest's exit status is preserved, and the pytest command is passed as arguments
    assert '"$@"' in script
    j = a.index("python")
    assert a[j:j + 4] == ["python", "-P", "-m", "pytest"] and j > i + 2


def test_wrapper_script_contains_no_untrusted_text():
    script = args()[args().index("-c") + 1]
    assert "/g" not in script and "img" not in script  # only constants and the nonce


def test_no_docker_socket_privilege_or_host_env():
    a = " ".join(args())
    assert "docker.sock" not in a
    assert "--privileged" not in a
    assert "--network host" not in a
    envs = [x for x in args() if "=" in x and not x.startswith("-") and x.isupper() is False]
    assert not any("KEY" in e or "TOKEN" in e or "SECRET" in e for e in envs)


def test_container_is_not_auto_removed_so_its_state_can_be_inspected():
    # D9: with --rm Docker deletes the container on exit, before the runner can read OOMKilled.
    assert "--rm" not in args()


# --- M9.1 R7: repository modules must never shadow the stdlib or pytest's own dependencies -----
def test_pythonpath_holds_only_the_collector_and_repo_roots_go_in_their_own_variable():
    a = args(source_roots=("src", "."))
    env = dict(x.split("=", 1) for x in a if x.startswith(("PYTHONPATH=", "REDFIRST_")))
    assert env["PYTHONPATH"] == "/plugin"  # repo roots here would precede the stdlib
    assert env["REDFIRST_SOURCE_ROOTS"] == "/repo/src:/repo"


def test_interpreter_runs_in_safe_path_mode_so_the_working_directory_is_not_on_sys_path():
    a = args()
    i = a.index("python")
    assert a[i + 1:i + 4] == ["-P", "-m", "pytest"]


def test_wrapper_kills_every_other_process_before_printing_the_report():
    """A child left running by the tests must not be able to print a block after the real one."""
    script = args()[args().index("-c") + 1]
    kill = script.index("os.kill(-1, signal.SIGKILL)")
    assert kill < script.index(REPORT_BEGIN.format(nonce=NONCE))
    assert script.index("status=$?") < kill  # pytest's exit status is captured first
