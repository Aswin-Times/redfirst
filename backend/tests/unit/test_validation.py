import pytest

from redfirst.analysis.index import FileInfo, RepoIndex
from redfirst.validation.policy import module_map, validate_test

MODULES = {"app": "app/__init__.py", "app.users": "app/users.py", "app.billing": "app/billing.py"}
TARGET = ["app/users.py"]

GOOD = """
from app.users import register

def test_control():
    assert register({"username": "a"}) == "a"

def test_reproduces_bug():
    assert register({"email": "x"}) is not None
"""


def v(code, targets=TARGET):
    return validate_test(code, MODULES, targets)


def test_good_test_passes_and_exercises_target():
    r = v(GOOD)
    assert r.ok, r.errors
    assert r.exercises_target and r.has_control_test


def test_module_attribute_access_counts_as_exercising_target():
    r = v("import app.users\n\ndef test_reproduces_bug():\n    app.users.register({})\n")
    assert r.ok, r.errors
    assert r.exercises_target


def test_helper_indirection_counts():
    code = ("from app.users import register\n\ndef _go():\n    return register({})\n\n"
            "def test_reproduces_bug():\n    _go()\n")
    assert v(code).exercises_target


def test_main_test_that_ignores_target_is_rejected():
    code = "from app.users import register\n\ndef test_reproduces_bug():\n    assert 1 == 2\n"
    r = v(code)
    assert not r.ok and any("never references" in e for e in r.errors)


def test_importing_non_target_repo_module_does_not_count():
    code = "from app.billing import charge\n\ndef test_reproduces_bug():\n    charge(1)\n"
    assert not v(code).ok


@pytest.mark.parametrize("mod", ["subprocess", "socket", "os", "ctypes", "urllib.request",
                                 "requests", "importlib", "shutil", "sys"])
def test_disallowed_imports(mod):
    r = v(f"import {mod}\n" + GOOD)
    assert not r.ok and any("import not allowed" in e for e in r.errors)


def test_relative_import_rejected():
    assert not v("from . import users\n" + GOOD).ok


@pytest.mark.parametrize("call", ["eval('1')", "exec('x=1')", "__import__('os')", "open('f')",
                                  "compile('1','f','eval')", "globals()"])
def test_forbidden_calls(call):
    code = GOOD + f"\ndef helper():\n    {call}\n"
    assert not v(code).ok


def test_dunder_escape_chain_rejected():
    code = GOOD + "\nx = ().__class__.__bases__[0].__subclasses__()\n"
    r = v(code)
    assert not r.ok and any("dunder" in e for e in r.errors)


def test_builtins_name_rejected():
    assert not v(GOOD + "\nb = __builtins__\n").ok


def test_syntax_error():
    r = v("def test_reproduces_bug(:\n")
    assert not r.ok and "syntax error" in r.errors[0]


def test_missing_or_duplicate_main_test():
    assert not v("from app.users import register\n").ok
    dup = GOOD + "\ndef test_reproduces_bug():\n    register({})\n"
    assert not v(dup).ok


def test_unknown_target_module_rejected():
    r = v(GOOD, targets=["app/nope.py"])
    assert not r.ok and any("not a repository file" in e for e in r.errors)


def test_empty_targets_rejected():
    assert not v(GOOD, targets=[]).ok


def test_size_limit():
    assert not v(GOOD + "\n" * 400).ok


def test_missing_control_is_only_a_warning():
    code = "from app.users import register\n\ndef test_reproduces_bug():\n    register({})\n"
    r = v(code)
    assert r.ok and not r.has_control_test and r.warnings


def test_test_classes_rejected():
    code = GOOD + "\nclass TestX:\n    def test_a(self):\n        pass\n"
    assert not v(code).ok


def test_module_map_handles_src_layout_and_skips_tests():
    idx = RepoIndex(files=[
        FileInfo(path="src/app/__init__.py", is_test=False),
        FileInfo(path="src/app/users.py", is_test=False),
        FileInfo(path="tests/test_users.py", is_test=True),
    ])
    assert module_map(idx, ["src"]) == {"app": "src/app/__init__.py",
                                         "app.users": "src/app/users.py"}
    flat = RepoIndex(files=[FileInfo(path="calc.py", is_test=False)])
    assert module_map(flat, ["."]) == {"calc": "calc.py"}
