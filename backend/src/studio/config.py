"""Settings from environment variables (and a local .env in development)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL, as a SQLAlchemy URL: postgresql+psycopg://user:pass@host:port/db
    database_url: str = "postgresql+psycopg://studio:studio@127.0.0.1:55433/studio"

    # Browser origins allowed to call the API with the session cookie.
    allowed_origins: list[str] = ["http://localhost:3000"]

    # Send the session cookie over HTTPS only. Turn off for plain-HTTP local dev.
    cookie_secure: bool = False
    session_hours: int = 12

    # Optional: lets "llm" nodes call OpenAI. Workflows without them run without it.
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
