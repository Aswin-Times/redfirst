"""Rank repo files by relevance to a bug report using deterministic signals only."""

import re
from pathlib import Path

from pydantic import BaseModel, Field

from redfirst.analysis.index import RepoIndex
from redfirst.analysis.traces import map_frames_to_repo, parse_traceback

_STOPWORDS = frozenset(
    "the and for with when that this from have has not but are was were will should would "
    "instead after before while into than then them they what which does did can could its "
    "use used using get got set raises raise error crash crashes returns return page user "
    "users value values valid invalid empty app application code test tests bug".split()
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

W_TRACE = 10.0
W_SYMBOL = 3.0
W_PATH = 2.0


class RankedFile(BaseModel):
    path: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)  # qualnames that matched


def keywords(*texts: str) -> list[str]:
    """Distinct lowercase identifiers/words from the report, minus stopwords. Order-stable."""
    seen: dict[str, None] = {}
    for text in texts:
        for w in _WORD.findall(text):
            low = w.lower()
            if low not in _STOPWORDS:
                seen.setdefault(low)
    return list(seen)


def _name_tokens(name: str) -> set[str]:
    # register_user / RegisterUser -> {"register", "user", "register_user"}
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower().split("_")
    return {p for p in parts if p} | {name.lower()}


def rank_files(
    index: RepoIndex, report_text: str, stack_trace: str = "", limit: int = 10
) -> list[RankedFile]:
    """Return non-test files ordered by score (ties broken by path). Evidence stays visible."""
    words = set(keywords(report_text))
    trace = parse_traceback(stack_trace) if stack_trace else None
    all_paths = [f.path for f in index.files]
    traced = {p: fr for p, fr in map_frames_to_repo(trace, all_paths)} if trace else {}

    scored: list[RankedFile] = []
    for f in index.files:
        if f.is_test:
            continue
        score, reasons, matched = 0.0, [], []
        if f.path in traced:
            score += W_TRACE
            reasons.append(f"appears in stack trace (line {traced[f.path].line})")
        stem_tokens = _name_tokens(Path(f.path).stem) | {
            t for part in Path(f.path).parts[:-1] for t in _name_tokens(part)
        }
        path_hits = sorted(words & stem_tokens)
        if path_hits:
            score += W_PATH * len(path_hits)
            reasons.append(f"path matches: {', '.join(path_hits)}")
        for sym in index.symbols_in(f.path):
            hits = words & _name_tokens(sym.name)
            if hits:
                score += W_SYMBOL * len(hits)
                matched.append(sym.qualname)
                reasons.append(f"symbol {sym.qualname} matches: {', '.join(sorted(hits))}")
        if score > 0:
            scored.append(RankedFile(path=f.path, score=score, reasons=reasons, symbols=matched))
    scored.sort(key=lambda r: (-r.score, r.path))
    return scored[:limit]
