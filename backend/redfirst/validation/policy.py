"""Static policy checks on a generated test before it is executed.

This is a correctness and hygiene gate, NOT a security boundary: a determined author can
evade static checks. Isolation is the sandbox's job (no network, read-only repo, limits).

Known gaps (documented in docs/threat-model.md): repository modules are untrusted code that
runs anyway, so names reachable through them (e.g. a module the repository imported) are not
policed; neither are internals of mock/fixture objects beyond the names listed below.
"""

import ast
import functools
import importlib
import types

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
ALLOWED_SUBMODULES = frozenset({"unittest.mock", "collections.abc"})
# Names that are rejected wherever they appear (calls, references, assignments).
FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open", "breakpoint", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "__builtins__", "__loader__", "__spec__",
})
FORBIDDEN_CALLS = FORBIDDEN_NAMES  # backwards-compatible alias
ALLOWED_DUNDERS = frozenset({"__name__", "__qualname__", "__doc__"})
# Attribute names that reach the import system, interpreter frames or mock internals.
GADGET_ATTRS = frozenset({
    "importorskip", "get_original", "getter", "pluginmanager", "import_plugin",
    "tb_frame", "f_globals", "f_locals", "f_builtins", "f_back", "f_code",
    "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame", "co_code", "func_globals",
})
# Public library API that a reproduction test never needs and that can import modules, write
# files, evaluate strings or end the process.
LIBRARY_DENY: dict[str, frozenset[str]] = {
    "pytest": frozenset({"importorskip", "main", "console_main", "exit",
                         "register_assert_rewrite", "freeze_includes"}),
    "io": frozenset({"open", "open_code", "FileIO"}),
    "operator": frozenset({"attrgetter", "methodcaller"}),
    "typing": frozenset({"get_type_hints", "ForwardRef", "evaluate_forward_ref"}),
}
DENY_PATHS = frozenset({"unittest.mock.patch.dict"})  # exposes real dicts such as sys.modules
# pytest is a test-time dependency of the sandbox image, not of the worker, so its permitted
# API is listed explicitly instead of being introspected.
_PYTEST_API = frozenset({
    "approx", "fixture", "mark", "param", "raises", "skip", "fail", "xfail", "warns",
    "deprecated_call", "MonkeyPatch", "LogCaptureFixture", "CaptureFixture", "ExceptionInfo",
    "FixtureRequest", "TempPathFactory", "RaisesGroup",
})


@functools.cache
def _library_api(module: str) -> frozenset[str]:
    """Public, non-module names of an allowed library, minus denied ones."""
    if module == "pytest":
        api = set(_PYTEST_API)
    else:
        mod = importlib.import_module(module)  # stdlib only: ALLOWED_LIBRARIES/SUBMODULES
        names = getattr(mod, "__all__", None) or [n for n in dir(mod) if not n.startswith("_")]
        api = {n for n in names if not n.startswith("_")
               and not isinstance(getattr(mod, n, None), types.ModuleType)}
    api |= {s.rpartition(".")[2] for s in ALLOWED_SUBMODULES if s.rpartition(".")[0] == module}
    return frozenset(api - LIBRARY_DENY.get(module, frozenset()))


def _is_library_module(name: str) -> bool:
    return name in ALLOWED_LIBRARIES or name in ALLOWED_SUBMODULES


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


def _chain(node: ast.Attribute) -> tuple[ast.Name | None, list[str]]:
    """``a.b.c`` -> (Name a, ["b", "c"]); the root is None if it is not a plain name."""
    attrs: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        attrs.append(cur.attr)
        cur = cur.value
    return (cur if isinstance(cur, ast.Name) else None), attrs[::-1]


def _library_chain_problem(origin: str, is_module: bool, attrs: list[str]) -> str | None:
    """Check ``origin.attr1.attr2...`` where ``origin`` is an imported library name."""
    module = origin if is_module else None
    path = origin
    for attr in attrs:
        if module is not None:
            sub = f"{module}.{attr}"
            if sub in ALLOWED_SUBMODULES:
                module = path = sub
                continue
            if attr in LIBRARY_DENY.get(module, ()):
                return f"{module}.{attr} is not allowed"
            if attr not in _library_api(module):
                return f"{module}.{attr} is not part of the allowed {module} API"
            module = None
        path = f"{path}.{attr}"
        if path in DENY_PATHS:
            return f"{path} is not allowed"
    return None


def _policy_problems(tree: ast.AST, repo_tops: set[str]) -> list[str]:
    """Imports, names and attribute access that the policy rejects (hygiene, not security)."""
    errors: list[str] = []
    library: dict[str, tuple[str, bool]] = {}  # local name -> (dotted origin, is a module)
    repo_names: set[str] = set()  # local names bound to repository code

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            errors.append("relative imports are not allowed")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in repo_tops:
                    repo_names.add(alias.asname or top)
                elif _is_library_module(alias.name):
                    # "import a.b" binds "a"; "import a.b as c" binds "c" to "a.b"
                    library[alias.asname or top] = (alias.name if alias.asname else top, True)
                else:
                    errors.append(f"import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in repo_tops:
                repo_names.update(a.asname or a.name for a in node.names)
                continue
            if not _is_library_module(node.module):
                errors.append(f"import not allowed: {node.module}")
                continue
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if alias.name in LIBRARY_DENY.get(node.module, ()) or alias.name in GADGET_ATTRS:
                    errors.append(f"{full} is not allowed")
                elif full in ALLOWED_SUBMODULES:
                    library[alias.asname or alias.name] = (full, True)
                elif alias.name == "*" or alias.name not in _library_api(node.module):
                    errors.append(f"{full} is not part of the allowed {node.module} API")
                else:
                    library[alias.asname or alias.name] = (full, False)

    parents = {child: parent for parent in ast.walk(tree)
               for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                errors.append(f"name not allowed: {node.id} (line {line})")
            elif node.id in library and library[node.id][1]:
                parent = parents.get(node)
                if not (isinstance(parent, ast.Attribute) and parent.value is node):
                    errors.append(f"library module '{node.id}' may only be used as "
                                  f"{node.id}.<name> (line {line})")
        elif isinstance(node, ast.Attribute):
            root, attrs = _chain(node)
            if node.attr.startswith("__") and node.attr not in ALLOWED_DUNDERS:
                errors.append(f"dunder attribute access not allowed: {node.attr} (line {line})")
            elif node.attr in GADGET_ATTRS:
                errors.append(f"attribute not allowed: {node.attr} (line {line})")
            elif node.attr.startswith("_") and node.attr not in ALLOWED_DUNDERS \
                    and (root is None or root.id not in repo_names):
                errors.append(f"private attribute access not allowed: {node.attr} (line {line}); "
                              "only repository code may be reached through private names")
            elif root is not None and root.id in library:
                origin, is_module = library[root.id]
                problem = _library_chain_problem(origin, is_module, attrs)
                if problem:
                    errors.append(f"{problem} (line {line})")
    return list(dict.fromkeys(errors))  # nested chains repeat the same finding


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

    # --- imports, names and attribute access ----------------------------------------------------
    errors.extend(_policy_problems(tree, repo_tops))

    bound_from_target: set[str] = set()  # local names that refer to target code
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if node.module in target_names or full in target_names:
                    bound_from_target.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in target_names:
                    bound_from_target.add(alias.asname or alias.name)

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
