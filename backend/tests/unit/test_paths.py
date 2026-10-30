"""D1: canonical repository-relative paths for traceback frames and contract targets."""

import pytest

from redfirst.verification.paths import canonical_target, repo_relative, same_path


@pytest.mark.parametrize(("file", "root", "expected"), [
    ("/repo/app/users.py", "/repo", "app/users.py"),
    ("/repo/src/app/users.py", "/repo", "src/app/users.py"),
    ("/repo/users.py", "/repo/", "users.py"),
    ("/repo//app/./users.py", "/repo", "app/users.py"),
    ("app/users.py", "/repo", "app/users.py"),  # relative frames are relative to the repo root
    # Windows host paths (local runs): separators, drive-letter case, mixed separators
    ("C:\\work\\repo\\app\\users.py", "C:\\work\\repo", "app/users.py"),
    ("c:\\work\\repo\\app\\users.py", "C:/work/repo", "app/users.py"),
    ("C:/Work/Repo/app/users.py", "c:\\work\\repo", "app/users.py"),
])
def test_paths_inside_the_repository(file, root, expected):
    assert repo_relative(file, root) == expected


@pytest.mark.parametrize(("file", "root"), [
    ("/usr/local/lib/python3.12/site-packages/lib/myutils.py", "/repo"),  # suffix collision
    ("/usr/local/lib/python3.12/site-packages/app/users.py", "/repo"),    # same tail elsewhere
    ("/repository/app/users.py", "/repo"),    # sibling directory sharing a prefix
    ("/repo/../etc/passwd", "/repo"),          # parent-directory escape
    ("../outside.py", "/repo"),                # relative escape
    ("/repo", "/repo"),                        # the root itself is not a file inside it
    ("/gen/test_redfirst.py", "/repo"),
    ("C:\\work\\repo2\\app\\users.py", "C:\\work\\repo"),
    ("D:\\work\\repo\\app\\users.py", "C:\\work\\repo"),
    ("", "/repo"),
])
def test_paths_outside_the_repository(file, root):
    assert repo_relative(file, root) is None


def test_posix_roots_are_case_sensitive():
    assert repo_relative("/Repo/app/users.py", "/repo") is None


@pytest.mark.parametrize(("target", "expected"), [
    ("app/users.py", "app/users.py"),
    ("app\\users.py", "app/users.py"),
    ("./app/users.py", "app/users.py"),
    ("app//users.py", "app/users.py"),
    ("users.py", "users.py"),
    ("/repo/app/users.py", None),
    ("../app/users.py", None),
    ("app/../../etc/passwd", None),
    ("C:/repo/app/users.py", None),
    ("", None),
    (".", None),
])
def test_canonical_target(target, expected):
    assert canonical_target(target) == expected


def test_same_path_normalises_separators_and_windows_case_only():
    assert same_path("C:\\w\\gen\\test_redfirst.py", "c:/w/gen/test_redfirst.py")
    assert same_path("/gen/test_redfirst.py", "/gen//test_redfirst.py")
    assert not same_path("/gen/Test_redfirst.py", "/gen/test_redfirst.py")
    assert not same_path("/gen/test_redfirst.py", "/repo/test_redfirst.py")
