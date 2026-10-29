"""Parse Python tracebacks from bug reports and map frames onto repo files."""

import re

from pydantic import BaseModel, Field

_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?', re.M)
_EXC = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))"
                  r"(?::\s*(?P<msg>.*))?$", re.M)
_THIRD_PARTY = ("site-packages", "dist-packages", "<frozen", "<string>")


class TraceFrame(BaseModel):
    file: str
    line: int
    function: str | None = None


class ParsedTrace(BaseModel):
    frames: list[TraceFrame] = Field(default_factory=list)
    exception_type: str | None = None
    message: str = ""


def parse_traceback(text: str) -> ParsedTrace:
    frames = [
        TraceFrame(file=m["file"], line=int(m["line"]), function=m["func"])
        for m in _FRAME.finditer(text)
    ]
    matches = list(_EXC.finditer(text))
    exc = matches[-1] if matches else None  # the final exception line
    return ParsedTrace(
        frames=frames,
        exception_type=exc["type"] if exc else None,
        message=(exc["msg"] or "").strip() if exc else "",
    )


def map_frames_to_repo(trace: ParsedTrace, repo_files: list[str]) -> list[tuple[str, TraceFrame]]:
    """Match each frame to the repo file with the longest common path suffix.

    Frames in site-packages or the stdlib are ignored; ambiguous or absent matches are dropped.
    """
    mapped: list[tuple[str, TraceFrame]] = []
    for frame in trace.frames:
        norm = frame.file.replace("\\", "/")
        if any(marker in norm for marker in _THIRD_PARTY):
            continue
        candidates = [f for f in repo_files if norm == f or norm.endswith("/" + f)]
        if candidates:
            mapped.append((max(candidates, key=len), frame))
    return mapped
