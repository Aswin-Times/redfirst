"""Best-effort removal of credentials from text before it is stored or shown.

Repository code runs in the sandbox with no secrets, but it can print anything it was able to
read (or invent strings that look like keys). This is defence in depth for stored logs, not a
guarantee: it only recognises common formats.
"""

import re

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"(?i)(?<=bearer )[A-Za-z0-9._~+/\-]{16,}=*"),
]
# name = value / name: value for secret-looking names; the name is kept, the value is hidden.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (\b[\w\-.]*(?:password|passwd|secret|token|api[_\-]?key|access[_\-]?key|private[_\-]?key)
    [\w\-.]*\s*[=:]\s*)
    (?:"[^"\n]*"|'[^'\n]*'|[^\s,;]+)
    """
)


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNMENT.sub(lambda m: m.group(1) + REDACTED, text)
