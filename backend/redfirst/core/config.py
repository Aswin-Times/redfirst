"""Application settings loaded from environment variables (prefix REDFIRST_)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDFIRST_", env_file=".env", extra="ignore")

    env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    database_url: str = "postgresql+psycopg://redfirst:redfirst@localhost:5432/redfirst"
    data_dir: Path = Path("./data")

    llm_provider: str = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_api_key: SecretStr | None = None  # if unset, the SDK resolves ANTHROPIC_API_KEY etc.
    llm_effort: str = "high"  # low | medium | high | xhigh | max
    llm_max_tokens: int = 16000
    llm_refusal_fallbacks: bool = True  # server-side fallback model on a safety refusal
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    max_generation_attempts: int = Field(default=3, ge=1, le=10)
    reproduction_runs: int = Field(default=3, ge=1, le=10)
    retention_days: int = Field(default=30, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
