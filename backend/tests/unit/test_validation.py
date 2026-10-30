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


# --- D2: known bypasses of the static policy -------------------------------------------------
# The validator is a hygiene gate for model-written code, not a security boundary (the sandbox
# is). These are the bypasses found in the audit plus their direct variants.
CALL_TARGET = "\ndef test_reproduces_bug():\n    register({})\n"
IMPORTS = "from app.users import register\n"


@pytest.mark.parametrize("snippet", [
    # dynamic import of a forbidden module through pytest
    "import pytest\nsp = pytest.importorskip('subprocess')\n",
    "from pytest import importorskip\n",
    "import pytest\nimp = getattr(pytest, 'importorskip')\n",
    # file writes through io (could overwrite the result report)
    "import io\nio.open('/out/report.json', 'w').write('{}')\n",
    "from io import open as io_open\n",
    "import io\nio.FileIO('/out/report.json', 'w')\n",
    "import io\nio.open_code('/repo/app/users.py')\n",
    # library modules passed around as values defeat attribute checks
    "import io\nalias = io\n",
    "import pytest\nholder = [pytest]\n",
    # string-based attribute access
    "x = getattr(object, 'mro')\n",
    "setattr(object, 'x', 1)\n",
    "f = getattr\n",
    # private attributes and known introspection gadgets
    "from unittest import mock\nimp = mock._importer\n",
    "from unittest.mock import _importer\n",
    "def helper(monkeypatch):\n    return monkeypatch._setattr\n",
    "from unittest import mock\nreal = mock.patch('app.users.register').get_original()\n",
    "def helper(request):\n    return request.config.pluginmanager\n",
    "import pytest\n\ndef helper():\n    with pytest.raises(KeyError) as e:\n        register({})\n"
    "    return e.tb.tb_frame.f_globals\n",
    # module attributes that are other modules, or process control
    "import typing\nsysmod = typing.sys\n",
    "import json\njson.codecs.open('/out/report.json', 'w')\n",
    "import pytest\npytest.exit('done', returncode=0)\n",
    "import pytest\npytest.main(['-p', 'os'])\n",
])
def test_known_bypasses_are_rejected(snippet):
    r = v(IMPORTS + snippet + CALL_TARGET)
    assert not r.ok, f"accepted: {snippet!r}"


@pytest.mark.parametrize("snippet", [
    "import pytest\n\ndef helper():\n    with pytest.raises(KeyError) as e:\n        register({})\n"
    "    assert e.type is KeyError and 'username' in str(e.value)\n",
    "import pytest\n\n@pytest.fixture\ndef payload():\n    return {}\n",
    "import pytest\n\n@pytest.mark.parametrize('n', [1, 2])\ndef helper(n):\n    assert n\n",
    "import pytest\nassert 0.1 + 0.2 == pytest.approx(0.3)\n",
    "import io\nbuf = io.StringIO('a,b')\n",
    "from io import BytesIO\nbuf = BytesIO(b'x')\n",
    "def helper(monkeypatch):\n    monkeypatch.setattr('app.users.register', lambda d: d)\n",
    "from decimal import Decimal\nassert isinstance(Decimal('1.1'), Decimal)\n",
    "import datetime\nwhen = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)\n",
    "import collections\nc = collections.Counter('aab')\n",
    "from collections.abc import Mapping\nassert isinstance({}, Mapping)\n",
    "import math\nassert math.isclose(math.sqrt(4), 2)\n",
    "import re\nassert re.fullmatch(r'a+', 'aa')\n",
    "import json\nassert json.loads('[1]') == [1]\n",
])
def test_legitimate_test_code_is_still_accepted(snippet):
    r = v(IMPORTS + snippet + CALL_TARGET)
    assert r.ok, r.errors


def test_rejection_messages_explain_the_rule():
    r = v(IMPORTS + "import pytest\nsp = pytest.importorskip('subprocess')\n" + CALL_TARGET)
    assert any("importorskip" in e for e in r.errors)
    r = v(IMPORTS + "import io\nio.open('x', 'w')\n" + CALL_TARGET)
    assert any("io.open" in e for e in r.errors)


# --- M9.1 R4: bypasses found in the M9 review (all of these ran in a real pytest process) --------
@pytest.mark.parametrize("snippet", [
    # string.Formatter.get_field walks dunder attribute chains without a dunder in the AST
    "import string\nsubs = string.Formatter().get_field('0.__class__.__base__', (0,), {})\n",
    "import string\nF = string.Formatter\n",
    "from string import Formatter\n",
    # unittest.mock internals expose the real objects being patched
    "from unittest import mock\n\ndef helper():\n    p = mock.patch('os.getcwd')\n    p.start()\n"
    "    return p.temp_original\n",
    "from unittest import mock\n\ndef helper():\n    p = mock.patch('os.getcwd')\n    p.start()\n"
    "    return p.target\n",
    "import unittest\n",
    "import unittest.mock\n",
    "from unittest.mock import patch\n",
    # reaching the collector plugin (and its `os` module) through pytest's hook machinery
    "def helper(request):\n    return request.config.hook.pytest_collectreport.get_hookimpls()\n",
    "def helper(pytestconfig):\n    return pytestconfig\n",
    "def helper(cache):\n    return cache\n",
    "helper = lambda request: request\n",
    "def helper(items):\n    return [i.plugin_name for i in items]\n",
])
def test_m9_review_bypasses_are_rejected(snippet):
    r = v(IMPORTS + snippet + CALL_TARGET)
    assert not r.ok, f"accepted: {snippet!r}"


def test_fixtures_that_do_not_expose_pytest_internals_are_still_allowed():
    fixture = ("import pytest\n\n@pytest.fixture\n"
               "def payload(tmp_path, monkeypatch, capsys):\n    return {}\n")
    code = IMPORTS + fixture + CALL_TARGET
    assert v(code).ok


# --- M9.1 R1: an assertion in test_reproduces_bug must depend on target code's result ----------
def reproduces(body: str, extra: str = "") -> str:
    return IMPORTS + extra + "\ndef test_reproduces_bug():\n" + body


@pytest.mark.parametrize("body", [
    "    register({'username': 'a'})\n    assert False\n",
    "    register({'username': 'a'})\n    assert 1 == 2\n",
    "    register({'username': 'a'})\n    assert not True\n",
    "    register({'username': 'a'})\n    assert 0\n",
    "    register({'username': 'a'})\n    assert 'x' == 'y'\n",
    "    assert register({'username': 'a'}) and False\n",
    "    assert False and register({'username': 'a'})\n",
    "    register({'username': 'a'})\n    raise AssertionError('always')\n",
    "    register({'username': 'a'})\n    raise AssertionError\n",
    "    x = register({'username': 'a'})\n    y = 5\n    assert y == 6\n",  # y not from target
    "    x = register({'username': 'a'})\n    assert x == 'a'\n    assert False\n",  # second assert
])
def test_assertions_that_ignore_the_target_result_are_rejected(body):
    r = v(reproduces(body))
    assert not r.ok and any("assert" in e.lower() for e in r.errors), r.errors


@pytest.mark.parametrize("body", [
    "    assert register({'username': 'a'}) == 'b'\n",
    "    x = register({'username': 'a'})\n    assert x == 'b'\n",
    # taint spreads through assignments
    "    x = register({'username': 'a'})\n    y = x.upper()\n    assert y == 'B'\n",
    "    x = register({'username': 'a'})\n    assert len(x) == 2 and x != 'a'\n",
    "    for r in [register({'username': 'a'})]:\n        assert r == 'zzz'\n",
    "    assert (n := register({'username': 'a'})) == 'zzz'\n",
    "    with pytest.raises(KeyError) as e:\n        register({})\n"
    "    assert 'username' not in str(e.value)\n",
    "    register({})\n",  # no assertion at all: the failure is whatever target code raises
])
def test_assertions_that_use_the_target_result_are_accepted(body):
    r = v(reproduces(body, "import pytest\n"))
    assert r.ok, r.errors


def test_assertion_flag_is_set_only_when_every_assertion_depends_on_target():
    with_assert = v(reproduces("    assert register({'username': 'a'}) == 'b'\n"))
    assert with_assert.ok and with_assert.asserts_on_target_result
    no_assert = v(reproduces("    register({})\n"))
    assert no_assert.ok and not no_assert.asserts_on_target_result  # nothing to rely on
