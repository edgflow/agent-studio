"""Settings from environment variables (and a local .env in development)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL, as a SQLAlchemy URL: postgresql+psycopg://user:pass@host:port/db
    database_url: str = "postgresql+psycopg://studio:studio@127.0.0.1:55433/studio"

    # Where the frontend lives; links in invitations point here.
    app_url: str = "http://localhost:3000"

    # Browser origins allowed to call the API with the session cookie.
    allowed_origins: list[str] = ["http://localhost:3000"]

    # Send the session cookie over HTTPS only. Turn off for plain-HTTP local dev.
    cookie_secure: bool = False
    session_hours: int = 12

    # Fernet keys that encrypt stored OAuth tokens: comma-separated, newest first.
    # Without one, connections are switched off. Make a key with Fernet.generate_key()
    # (the command is in .env.example).
    token_encryption_keys: str | None = None

    # A GitHub OAuth app (github.com/settings/developers), with the callback URL
    # {app_url}/api/connections/github/callback.
    github_client_id: str | None = None
    github_client_secret: str | None = None

    # The local OAuth provider in devtools/oauth_provider.py, for development and demos.
    dev_oauth_url: str | None = None  # e.g. http://127.0.0.1:8010
    dev_oauth_client_id: str = "agent-studio-dev"
    dev_oauth_client_secret: str | None = None

    # Optional: lets "llm" nodes call OpenAI. Workflows without them run without it.
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
