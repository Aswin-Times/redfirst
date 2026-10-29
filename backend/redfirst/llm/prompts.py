"""Versioned prompt templates loaded from ``backend/prompts/<name>.<version>.md``.

File format: a ``## system`` section and a ``## user`` section. Placeholders use
``string.Template`` syntax (``$name``); a missing variable is an error, not a blank.
"""

from dataclasses import dataclass
from pathlib import Path
from string import Template

from redfirst.llm.base import LLMRequest

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    system: str
    user: str

    def render(self, **values: str) -> LLMRequest:
        return LLMRequest(
            system=Template(self.system).substitute(values),
            user=Template(self.user).substitute(values),
            prompt_name=self.name,
            prompt_version=self.version,
        )


def load_prompt(name: str, version: str, directory: Path = PROMPTS_DIR) -> PromptTemplate:
    text = (directory / f"{name}.{version}.md").read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    if set(sections) != {"system", "user"}:
        raise ValueError(f"prompt {name}.{version} needs exactly '## system' and '## user'")
    return PromptTemplate(name, version, "\n".join(sections["system"]).strip(),
                          "\n".join(sections["user"]).strip())
