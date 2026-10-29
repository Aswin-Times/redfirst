from pathlib import Path

from redfirst.analysis.index import index_repo
from redfirst.analysis.ranking import keywords, rank_files
from redfirst.analysis.search import search
from redfirst.analysis.traces import map_frames_to_repo, parse_traceback

TRACE = '''Traceback (most recent call last):
  File "/srv/app/main.py", line 10, in handle
    return register_user(data)
  File "/srv/app/app/users.py", line 7, in register_user
    name = data["username"]
  File "/usr/lib/python3.12/site-packages/foo/bar.py", line 3, in helper
KeyError: 'username'
'''


def make_repo(root: Path) -> Path:
    files = {
        "app/__init__.py": "",
        "app/users.py": (
            '"""User registration."""\n'
            "class Registry:\n"
            "    def add(self, name, email=None):\n"
            "        return name\n\n"
            "def register_user(data):\n"
            '    """Register a user."""\n'
            '    return data["username"]\n'
        ),
        "app/billing.py": "def charge(amount):\n    return amount\n",
        "tests/test_users.py": "from app.users import register_user\n\ndef test_a():\n    pass\n",
        "broken.py": "def oops(:\n",
    }
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def test_index_symbols_signatures_and_imports(tmp_path):
    idx = index_repo(make_repo(tmp_path))
    by_qual = {s.qualname: s for s in idx.symbols}
    assert by_qual["register_user"].signature == "register_user(data)"
    assert by_qual["register_user"].docstring == "Register a user."
    assert by_qual["Registry.add"].kind == "method"
    assert by_qual["Registry.add"].signature == "add(self, name, email=None)"
    test_file = next(f for f in idx.files if f.path == "tests/test_users.py")
    assert test_file.is_test and test_file.imports == ["app.users"]


def test_syntax_errors_are_recorded_not_swallowed(tmp_path):
    idx = index_repo(make_repo(tmp_path))
    assert "broken.py" in idx.parse_errors
    assert "SyntaxError" in idx.parse_errors["broken.py"]
    assert all(f.path != "broken.py" for f in idx.files)


def test_parse_traceback():
    t = parse_traceback(TRACE)
    assert t.exception_type == "KeyError" and t.message == "'username'"
    assert [f.function for f in t.frames] == ["handle", "register_user", "helper"]


def test_map_frames_ignores_site_packages_and_uses_longest_suffix():
    mapped = map_frames_to_repo(parse_traceback(TRACE), ["main.py", "app/users.py", "users.py"])
    assert [p for p, _ in mapped] == ["main.py", "app/users.py"]


def test_keywords_drop_stopwords():
    assert keywords("The app crashes when username is empty") == ["username"]


def test_ranking_prefers_trace_and_symbol_matches(tmp_path):
    idx = index_repo(make_repo(tmp_path))
    ranked = rank_files(idx, "registration crashes: register user with empty username", TRACE)
    assert ranked[0].path == "app/users.py"
    assert "register_user" in ranked[0].symbols
    assert any("stack trace" in r for r in ranked[0].reasons)
    assert all(r.path != "tests/test_users.py" for r in ranked)
    assert "app/billing.py" not in [r.path for r in ranked]


def test_ranking_without_trace_uses_names(tmp_path):
    idx = index_repo(make_repo(tmp_path))
    ranked = rank_files(idx, "charge amount is wrong")
    assert ranked[0].path == "app/billing.py"


def test_search_python_fallback(tmp_path):
    make_repo(tmp_path)
    hits = search(tmp_path, "REGISTER_user", use_rg=False)
    assert [(h.file, h.line) for h in hits][:1] == [("app/users.py", 6)]


def test_search_rg_matches_fallback(tmp_path):
    make_repo(tmp_path)
    assert search(tmp_path, "username", use_rg=True) == search(tmp_path, "username", use_rg=False)


def test_search_term_starting_with_dash_and_blank(tmp_path):
    make_repo(tmp_path)
    assert search(tmp_path, "--files") == []
    assert search(tmp_path, "   ") == []
