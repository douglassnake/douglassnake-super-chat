from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Super Chat API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://superchat:superchat@localhost:5432/superchat"

    github_token: str | None = None
    github_api_url: str = "https://api.github.com"

    google_access_token: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_refresh_token: str | None = None
    google_oauth_token_url: str = "https://oauth2.googleapis.com/token"
    google_drive_api_url: str = "https://www.googleapis.com/drive/v3"
    google_calendar_api_url: str = "https://www.googleapis.com/calendar/v3"

    # M8.5: execução local isolada. Permanece desligada por padrão.
    executor_isolated_enabled: bool = False
    executor_worktree_root: str | None = None
    executor_timeout_seconds: float = 60.0
    executor_max_timeout_seconds: float = 300.0
    executor_output_max_bytes: int = 65_536
    executor_env_allowlist: str = "SYSTEMROOT,TEMP,TMP,TMPDIR"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
