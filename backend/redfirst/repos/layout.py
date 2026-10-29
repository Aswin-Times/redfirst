"""Detect Python project layout without assuming a fixed structure."""

from pathlib import Path

from pydantic import BaseModel, Field

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}
_MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "poetry.lock")


class RepoLayout(BaseModel):
    layout: str  # "src" | "flat" | "unknown"
    source_roots: list[str] = Field(default_factory=list)  # dirs to put on sys.path
    packages: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)
    requirements_files: list[str] = Field(default_factory=list)
    test_dirs: list[str] = Field(default_factory=list)
    conftest_files: list[str] = Field(default_factory=list)
    pytest_config: str | None = None
    python_file_count: int = 0


def _walk(root: Path):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        yield p, rel.as_posix()


def _top_level_packages(base: Path) -> list[str]:
    return sorted(
        d.name for d in base.iterdir()
        if d.is_dir() and d.name not in _SKIP_DIRS and (d / "__init__.py").is_file()
        and not d.name.startswith("test")
    )


def detect_layout(root: Path) -> RepoLayout:
    """Inspect an extracted repo. ``root`` must be a real directory."""
    root = root.resolve()
    manifests, reqs, tests, confs = [], [], set(), []
    pytest_config = None
    py_count = 0
    for path, rel in _walk(root):
        if not path.is_file() or path.is_symlink():
            continue
        name = path.name
        if name in _MANIFESTS and "/" not in rel:
            manifests.append(rel)
        if name.startswith("requirements") and name.endswith(".txt") and "/" not in rel:
            reqs.append(rel)
        if name == "conftest.py":
            confs.append(rel)
        if name in ("pytest.ini", "tox.ini") and "/" not in rel and pytest_config is None:
            pytest_config = rel
        if name == "pyproject.toml" and "/" not in rel:
            if "[tool.pytest" in path.read_text(encoding="utf-8", errors="replace"):
                pytest_config = rel
        if name.endswith(".py"):
            py_count += 1
            if name.startswith("test_") or name.endswith("_test.py"):
                tests.add(str(Path(rel).parent.as_posix()))

    src = root / "src"
    if src.is_dir() and _top_level_packages(src):
        layout, roots, packages = "src", ["src"], _top_level_packages(src)
    elif _top_level_packages(root):
        layout, roots, packages = "flat", ["."], _top_level_packages(root)
    elif py_count:
        layout, roots, packages = "flat", ["."], []  # loose modules at the top level
    else:
        layout, roots, packages = "unknown", [], []

    return RepoLayout(
        layout=layout, source_roots=roots, packages=packages, manifests=sorted(manifests),
        requirements_files=sorted(reqs), test_dirs=sorted(tests), conftest_files=sorted(confs),
        pytest_config=pytest_config, python_file_count=py_count,
    )
