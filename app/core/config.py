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

    executor_isolated_enabled: bool = False
    executor_worktree_root: str | None = None
    executor_timeout_seconds: float = 60.0
    executor_max_timeout_seconds: float = 300.0
    executor_output_max_bytes: int = 65_536
    executor_env_allowlist: str = "SYSTEMROOT,TEMP,TMP,TMPDIR"

    executor_worker_backend: str = "subprocess-sandbox"
    executor_worker_cpu_seconds: int = 120
    executor_worker_memory_mb: int = 1024
    executor_worker_pids: int = 128
    executor_worker_nofile: int = 256
    executor_worker_file_size_mb: int = 64
    executor_container_runtime: str = "docker"
    executor_container_image: str = "python:3.13-slim"

    executor_worker_lease_seconds: int = 120
    executor_worker_max_attempts: int = 3

    executor_modify_max_files: int = 20
    executor_modify_max_operations: int = 40
    executor_modify_max_total_write_bytes: int = 65_536
    executor_modify_max_patch_bytes: int = 65_536

    executor_git_staging_root: str | None = None
    executor_git_author_name: str = "Super Chat Executor"
    executor_git_author_email: str = "superchat-executor@localhost"

    # M8.12: remote inicial sem credenciais/rede externa. Deve apontar para
    # um repositório bare local absoluto controlado pelo servidor.
    executor_git_publish_remote: str | None = None
    executor_git_publish_remote_id: str = "controlled-bare"

    # M8.13: escrita GitHub para PR, separada do worker. DESLIGADA por padrão.
    executor_github_write_enabled: bool = False
    executor_github_write_token: str | None = None
    executor_github_write_repository: str | None = None
    executor_github_pr_base_branch: str = "main"
    executor_github_pr_draft: bool = True

    # M8.14: publicação autenticada de branch GitHub via credential broker.
    # Mantém token separado do writer de PR para menor privilégio operacional.
    executor_github_publish_enabled: bool = False
    executor_github_publish_token: str | None = None
    executor_github_publish_repository: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
