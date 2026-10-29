"""Deterministic AST index of a Python repository."""

import ast
from pathlib import Path

from pydantic import BaseModel, Field

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}
MAX_FILE_BYTES = 1024 * 1024


class Symbol(BaseModel):
    kind: str  # "function" | "class" | "method"
    name: str
    qualname: str
    file: str  # posix path relative to the repo root
    lineno: int
    end_lineno: int
    signature: str = ""
    docstring: str | None = None


class FileInfo(BaseModel):
    path: str
    is_test: bool
    imports: list[str] = Field(default_factory=list)  # imported module names, as written


class RepoIndex(BaseModel):
    files: list[FileInfo] = Field(default_factory=list)
    symbols: list[Symbol] = Field(default_factory=list)
    parse_errors: dict[str, str] = Field(default_factory=dict)  # path -> reason
    skipped: dict[str, str] = Field(default_factory=dict)  # path -> reason

    def symbols_in(self, path: str) -> list[Symbol]:
        return [s for s in self.symbols if s.file == path]


def is_test_path(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def iter_python_files(root: Path):
    """Yield (path, relative posix path) for regular, non-symlink .py files."""
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield p, rel.as_posix()


def _imports(tree: ast.AST) -> list[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return sorted(found)


def _walk_defs(body, rel: str, prefix: str, in_class: bool, out: list[Symbol]) -> None:
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = f"{prefix}{node.name}"
            out.append(Symbol(
                kind="method" if in_class else "function", name=node.name, qualname=qual,
                file=rel, lineno=node.lineno, end_lineno=node.end_lineno or node.lineno,
                signature=f"{node.name}({ast.unparse(node.args)})",
                docstring=ast.get_docstring(node),
            ))
        elif isinstance(node, ast.ClassDef):
            qual = f"{prefix}{node.name}"
            out.append(Symbol(
                kind="class", name=node.name, qualname=qual, file=rel, lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno, docstring=ast.get_docstring(node),
            ))
            _walk_defs(node.body, rel, qual + ".", True, out)


def index_repo(root: Path) -> RepoIndex:
    root = root.resolve()
    idx = RepoIndex()
    for path, rel in iter_python_files(root):
        if path.is_symlink():
            idx.skipped[rel] = "symlink"
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            idx.skipped[rel] = "file too large"
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            idx.parse_errors[rel] = f"{type(exc).__name__}: {exc}"
            continue
        idx.files.append(FileInfo(path=rel, is_test=is_test_path(rel), imports=_imports(tree)))
        _walk_defs(tree.body, rel, "", False, idx.symbols)
    return idx
