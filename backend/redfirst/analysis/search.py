"""Text search over a repo: ripgrep when available, pure Python otherwise.

Both paths return identical, sorted results so behaviour does not depend on the host.
"""

import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

from redfirst.analysis.index import MAX_FILE_BYTES, SKIP_DIRS


class Hit(BaseModel):
    file: str
    line: int
    text: str


def _rg_search(root: Path, term: str, limit: int) -> list[Hit] | None:
    rg = shutil.which("rg")
    if not rg:
        return None
    args = [rg, "--no-heading", "--line-number", "--fixed-strings", "--ignore-case",
            "--no-config", "--no-messages", "--glob", "*.py", "--glob", "!.git", "--no-ignore",
            "--max-filesize", str(MAX_FILE_BYTES), "--", term, "."]
    for d in SKIP_DIRS:
        args[-3:-3] = ["--glob", f"!{d}"]
    try:
        proc = subprocess.run(args, cwd=root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):  # 1 = no matches
        return None
    hits = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[1].isdigit():
            hits.append(Hit(file=parts[0].replace("\\", "/").removeprefix("./"),
                            line=int(parts[1]), text=parts[2].strip()[:300]))
    return hits


def _py_search(root: Path, term: str) -> list[Hit]:
    needle = term.lower()
    hits: list[Hit] = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or p.is_symlink():
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if needle in line.lower():
                hits.append(Hit(file=rel.as_posix(), line=n, text=line.strip()[:300]))
    return hits


def search(root: Path, term: str, limit: int = 50, use_rg: bool = True) -> list[Hit]:
    """Case-insensitive literal search of ``term`` in .py files."""
    if not term.strip():
        return []
    root = root.resolve()
    hits = _rg_search(root, term, limit) if use_rg else None
    if hits is None:
        hits = _py_search(root, term)
    hits.sort(key=lambda h: (h.file, h.line))
    return hits[:limit]
