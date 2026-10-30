from pathlib import Path

from redfirst.sandbox.docker_cmd import SandboxSpec, build_docker_args


def args(**kw):
    spec = SandboxSpec(image="img", name="c1", repo_dir=Path("/r"), gen_dir=Path("/g"),
                       plugin_dir=Path("/p"), out_dir=Path("/o"), **kw)
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


def test_only_the_output_mount_is_writable():
    a = args()
    mounts = [a[i + 1] for i, x in enumerate(a) if x == "-v"]
    assert len(mounts) == 4
    writable = [m for m in mounts if m.endswith(":rw")]
    assert writable == [f"{Path('/o')}:/out:rw"]
    assert all(m.endswith(":ro") for m in mounts if m not in writable)


def test_no_docker_socket_privilege_or_host_env():
    a = " ".join(args())
    assert "docker.sock" not in a
    assert "--privileged" not in a
    assert "--network host" not in a
    envs = [x for x in args() if "=" in x and not x.startswith("-") and x.isupper() is False]
    assert not any("KEY" in e or "TOKEN" in e or "SECRET" in e for e in envs)


def test_source_roots_go_on_pythonpath():
    a = args(source_roots=("src", "."))
    env = next(x for x in a if x.startswith("PYTHONPATH="))
    assert env == "PYTHONPATH=/plugin:/repo/src:/repo"


def test_container_is_not_auto_removed_so_its_state_can_be_inspected():
    # D9: with --rm Docker deletes the container on exit, before the runner can read OOMKilled.
    assert "--rm" not in args()
