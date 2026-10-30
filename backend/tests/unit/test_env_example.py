"""Every variable in .env.example must be a real setting (no typos silently ignored)."""

from pathlib import Path

from redfirst.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def test_env_example_names_only_existing_settings():
    names = [line.split("=", 1)[0] for line in ENV_EXAMPLE.read_text().splitlines()
             if line and not line.startswith("#") and "=" in line]
    known = {f"REDFIRST_{field.upper()}" for field in Settings.model_fields}
    assert names and set(names) <= known, set(names) - known
