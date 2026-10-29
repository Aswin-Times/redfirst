"""Assemble the bounded code context sent to the model. Only relevant files, size-capped."""

from pathlib import Path

from redfirst.analysis.index import RepoIndex
from redfirst.analysis.ranking import RankedFile

MAX_FILES = 5
MAX_FILE_CHARS = 6_000
MAX_TOTAL_CHARS = 24_000
MAX_TEST_EXAMPLE_CHARS = 2_000


def _read(root: Path, rel: str, limit: int) -> str:
    text = (root / rel).read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= limit else text[:limit] + "\n# ... [truncated by REDFIRST]\n"


def build_evidence(
    root: Path, index: RepoIndex, ranked: list[RankedFile], modules: dict[str, str]
) -> tuple[str, list[str]]:
    """Return (evidence text, file paths included). Deterministic for the same inputs."""
    root = root.resolve()
    parts: list[str] = []
    included: list[str] = []
    budget = MAX_TOTAL_CHARS
    path_to_module = {p: m for m, p in modules.items()}

    for rf in ranked[:MAX_FILES]:
        if budget <= 0:
            break
        body = _read(root, rf.path, min(MAX_FILE_CHARS, budget))
        budget -= len(body)
        included.append(rf.path)
        sigs = "\n".join(
            f"  line {s.lineno}: {s.signature or s.qualname}" for s in index.symbols_in(rf.path)
        )
        parts.append(
            f'<file path="{rf.path}" import_as="{path_to_module.get(rf.path, "?")}">\n'
            f"why selected: {'; '.join(rf.reasons) or 'n/a'}\n"
            f"symbols:\n{sigs or '  (none)'}\n"
            f"source:\n{body}\n</file>"
        )

    selected = set(included)
    example = next(
        (f for f in index.files if f.is_test and not f.path.endswith("conftest.py")
         and any(modules.get(i) in selected for i in f.imports)),
        None,
    )
    if example:
        parts.append(f'<existing_test path="{example.path}">\n'
                     f"{_read(root, example.path, MAX_TEST_EXAMPLE_CHARS)}\n</existing_test>")
    if not included:
        parts.append("(no repository file matched the report; importable modules: "
                     + ", ".join(sorted(modules)[:50]) + ")")
    return "\n\n".join(parts), included
