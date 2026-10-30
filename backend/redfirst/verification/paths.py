"""Canonical paths for deciding whether a traceback frame is repository code.

A frame counts as target code only when its file lies *inside* the repository root as seen by
the test process and its repository-relative path equals a contract target exactly. Suffix
matching ("…/myutils.py" ends with "utils.py") is never used.

Paths may come from the Docker sandbox (POSIX, e.g. ``/repo/app/users.py``) or from a local
Windows run (``C:\\work\\repo\\app\\users.py``), so both separators are normalised. Drive
letters, and Windows paths generally, compare case-insensitively; POSIX paths do not.
"""

import posixpath
import re

_DRIVE = re.compile(r"^[A-Za-z]:")


def _normalise(path: str) -> str:
    path = path.replace("\\", "/")
    drive = ""
    if _DRIVE.match(path):
        drive, path = path[:2].upper(), path[2:]
    path = posixpath.normpath(path) if path else path
    return drive + path


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or bool(_DRIVE.match(path))


def _is_windows(path: str) -> bool:
    return bool(_DRIVE.match(path))


def same_path(a: str, b: str) -> bool:
    """Whether two absolute paths name the same file (no filesystem access)."""
    na, nb = _normalise(a), _normalise(b)
    if _is_windows(na) or _is_windows(nb):
        return na.lower() == nb.lower()
    return na == nb


def repo_relative(file: str, repo_root: str) -> str | None:
    """``file`` relative to ``repo_root`` as a POSIX path, or None if it is outside the root.

    Relative frame paths are interpreted relative to the repository root, which is the
    working directory of the test process.
    """
    if not file or not repo_root:
        return None
    root = _normalise(repo_root).rstrip("/") or "/"
    path = _normalise(file)
    if not _is_absolute(path):
        path = _normalise(f"{root}/{path}")
    prefix = root if root.endswith("/") else root + "/"
    head = path[:len(prefix)]
    matches = head.lower() == prefix.lower() if _is_windows(root) else head == prefix
    if not matches:
        return None
    rel = path[len(prefix):]
    if not rel or rel == ".." or rel.startswith("../"):
        return None
    return rel


def canonical_target(target: str) -> str | None:
    """A contract target as a clean repository-relative POSIX path, or None if unsafe."""
    if not target:
        return None
    path = target.replace("\\", "/")
    if _is_absolute(path):
        return None
    path = posixpath.normpath(path)
    if path in (".", "..") or path.startswith("../"):
        return None
    return path
