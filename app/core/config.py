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

    # M8.5/M8.6: execução isolada. Permanece desligada por padrão.
    executor_isolated_enabled: bool = False
    executor_worktree_root: str | None = None
    executor_timeout_seconds: float = 60.0
    executor_max_timeout_seconds: float = 300.0
    executor_output_max_bytes: int = 65_536
    executor_env_allowlist: str = "SYSTEMROOT,TEMP,TMP,TMPDIR"

    # O worker roda em processo separado da API. `subprocess-sandbox` funciona
    # sem runtime externo; `container` exige runtime/imagem administrados pelo servidor.
    executor_worker_backend: str = "subprocess-sandbox"
    executor_worker_cpu_seconds: int = 120
    executor_worker_memory_mb: int = 1024
    executor_worker_pids: int = 128
    executor_worker_nofile: int = 256
    executor_worker_file_size_mb: int = 64
    executor_container_runtime: str = "docker"
    executor_container_image: str = "python:3.13-slim"

    # M8.7: proveniência/reconciliação. O cliente não escolhe estes limites.
    executor_worker_lease_seconds: int = 120
    executor_worker_max_attempts: int = 3

    # M8.8: alteração efêmera. Limites exclusivamente server-side.
    executor_modify_max_files: int = 20
    executor_modify_max_operations: int = 40
    executor_modify_max_total_write_bytes: int = 65_536
    executor_modify_max_patch_bytes: int = 65_536

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
