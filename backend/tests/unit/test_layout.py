from pathlib import Path

from redfirst.repos.layout import detect_layout


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def test_src_layout(tmp_path):
    write(tmp_path, {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "src/app/__init__.py": "",
        "src/app/users.py": "",
        "tests/test_users.py": "",
        "tests/conftest.py": "",
        "requirements.txt": "pytest\n",
    })
    lay = detect_layout(tmp_path)
    assert lay.layout == "src"
    assert lay.source_roots == ["src"]
    assert lay.packages == ["app"]
    assert lay.test_dirs == ["tests"]
    assert lay.conftest_files == ["tests/conftest.py"]
    assert lay.pytest_config == "pyproject.toml"
    assert lay.requirements_files == ["requirements.txt"]


def test_flat_package_layout(tmp_path):
    write(tmp_path, {"app/__init__.py": "", "app/a.py": "", "setup.py": ""})
    lay = detect_layout(tmp_path)
    assert (lay.layout, lay.packages, lay.manifests) == ("flat", ["app"], ["setup.py"])


def test_loose_modules(tmp_path):
    write(tmp_path, {"calc.py": "", "test_calc.py": ""})
    lay = detect_layout(tmp_path)
    assert lay.layout == "flat" and lay.packages == [] and lay.test_dirs == ["."]


def test_empty_repo_is_unknown(tmp_path):
    write(tmp_path, {"README.md": "hi"})
    assert detect_layout(tmp_path).layout == "unknown"


def test_skips_vendored_dirs(tmp_path):
    write(tmp_path, {"calc.py": "", ".venv/lib/x.py": "", "node_modules/y.py": ""})
    assert detect_layout(tmp_path).python_file_count == 1
