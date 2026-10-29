"""Static policy checks on a generated test before it is executed.

This is a correctness and hygiene gate, NOT a security boundary: a determined author can
evade static checks. Isolation is the sandbox's job (no network, read-only repo, limits).
"""

import ast

from pydantic import BaseModel, Field

from redfirst.analysis.index import RepoIndex
from redfirst.sandbox.results import CONTROL_TEST, MAIN_TEST

MAX_LINES = 300
MAX_BYTES = 20_000

ALLOWED_LIBRARIES = frozenset({
    "pytest", "re", "json", "math", "decimal", "fractions", "datetime", "collections",
    "itertools", "functools", "dataclasses", "typing", "enum", "string", "copy", "uuid",
    "textwrap", "contextlib", "unittest", "operator", "statistics", "random", "io",
})
FORBIDDEN_CALLS = frozenset({
    "eval", "exec", "compile", "__import__", "open", "breakpoint", "input",
    "globals", "locals", "vars",
})
ALLOWED_DUNDERS = frozenset({"__name__", "__qualname__", "__doc__"})


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    exercises_target: bool = False
    has_control_test: bool = False


def module_map(index: RepoIndex, source_roots: list[str]) -> dict[str, str]:
    """Importable dotted module name -> repo file path, for each configured source root."""
    roots = sorted({r.strip("./") for r in source_roots} or {""}, key=len, reverse=True)
    out: dict[str, str] = {}
    for f in index.files:
        if f.is_test:
            continue
        for root in roots:
            prefix = f"{root}/" if root else ""
            if not f.path.startswith(prefix):
                continue
            parts = f.path[len(prefix):].removesuffix(".py").split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                out.setdefault(".".join(parts), f.path)
            break
    return out


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def validate_test(
    code: str, modules: dict[str, str], target_modules: list[str]
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if len(code.encode("utf-8")) > MAX_BYTES or code.count("\n") + 1 > MAX_LINES:
        errors.append(f"test exceeds {MAX_LINES} lines or {MAX_BYTES} bytes")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        errors.append(f"syntax error: {exc.msg} (line {exc.lineno})")
        return ValidationResult(ok=False, errors=errors)

    repo_tops = {m.split(".")[0] for m in modules}
    unknown_targets = [t for t in target_modules if t not in modules.values()]
    if not target_modules:
        errors.append("contract names no target_modules")
    for t in unknown_targets:
        errors.append(f"target module is not a repository file: {t}")
    target_names = {name for name, path in modules.items() if path in target_modules}

    # --- imports -------------------------------------------------------------------------
    bound_from_target: set[str] = set()  # local names that refer to target code
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            errors.append("relative imports are not allowed")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            for mod in filter(None, mods):
                top = mod.split(".")[0]
                if top not in ALLOWED_LIBRARIES and top not in repo_tops:
                    errors.append(f"import not allowed: {mod}")
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    full = f"{node.module}.{alias.name}"
                    if node.module in target_names or full in target_names:
                        bound_from_target.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in target_names:
                        bound_from_target.add(alias.asname or alias.name)

    # --- forbidden calls and attribute tricks -------------------------------------------------
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                errors.append(f"call not allowed: {node.func.id}() (line {node.lineno})")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") \
                and node.attr not in ALLOWED_DUNDERS:
            errors.append(f"dunder attribute access not allowed: {node.attr} (line {node.lineno})")
        if isinstance(node, ast.Name) and node.id in ("__builtins__", "__loader__", "__spec__"):
            errors.append(f"name not allowed: {node.id} (line {node.lineno})")

    # --- required structure -------------------------------------------------------------------
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    names = [f.name for f in funcs]
    for required in (MAIN_TEST,):
        if names.count(required) != 1:
            errors.append(f"module must define exactly one top-level {required}()")
    if names.count(CONTROL_TEST) > 1:
        errors.append(f"{CONTROL_TEST}() defined more than once")
    has_control = CONTROL_TEST in names
    if not has_control:
        warnings.append("no test_control(): setup problems cannot be told apart from the bug")
    extra_tests = [n for n in names if n.startswith("test_") and n not in (MAIN_TEST, CONTROL_TEST)]
    if extra_tests:
        warnings.append(f"extra tests are ignored by the verifier: {', '.join(extra_tests)}")
    if any(isinstance(n, ast.ClassDef) and n.name.startswith("Test") for n in tree.body):
        errors.append("test classes are not supported; use top-level functions")

    # --- does the main test reach target code? -------------------------------------------------
    def references_target(fn: ast.AST, seen: set[str]) -> bool:
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id in bound_from_target:
                return True
            if isinstance(node, ast.Attribute):
                dotted = _dotted(node)
                if dotted and any(dotted == t or dotted.startswith(t + ".") for t in target_names):
                    return True
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                helper = next((f for f in funcs if f.name == node.func.id), None)
                if helper is not None and helper.name not in seen:
                    if references_target(helper, seen | {helper.name}):
                        return True
        return False

    main = next((f for f in funcs if f.name == MAIN_TEST), None)
    exercises = bool(main) and references_target(main, {MAIN_TEST})
    if main is not None and not exercises and not unknown_targets:
        errors.append(f"{MAIN_TEST}() never references code imported from the target modules")

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings,
                            exercises_target=exercises, has_control_test=has_control)
