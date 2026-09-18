from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Super Chat API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://superchat:superchat@localhost:5432/superchat"
    github_token: str | None = None
    github_api_url: str = "https://api.github.com"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
