from __future__ import annotations

from typing import Protocol

from app.core.config import Settings
from app.secret_store import SecretStore, SecretStoreError, SettingsSecretStore, build_secret_store


class CredentialUnavailable(RuntimeError):
    pass


class SecretLease:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Secret lease cannot be empty")
        self._value = cleaned

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<SecretLease [REDACTED]>"

    def __str__(self) -> str:
        return "[REDACTED]"


class CredentialBroker(Protocol):
    def acquire_github_publish_token(self, repository: str) -> SecretLease: ...
    def acquire_github_pr_token(self, repository: str) -> SecretLease: ...


class SecretStoreCredentialBroker:
    """Repository-scoped credentials resolved only when an effect starts."""

    def __init__(self, settings: Settings, store: SecretStore | None = None) -> None:
        self._settings = settings
        self._store = store or build_secret_store(settings)
        self._publish_enabled = bool(settings.executor_github_publish_enabled)
        self._publish_repository = str(settings.executor_github_publish_repository or "").strip().strip("/")
        self._pr_enabled = bool(settings.executor_github_write_enabled)
        self._pr_repository = str(settings.executor_github_write_repository or "").strip().strip("/")

    @staticmethod
    def _authorized(requested: str, configured: str) -> bool:
        return bool(configured and requested.lower() == configured.lower())

    def _acquire(self, name: str) -> SecretLease:
        try:
            secret = self._store.acquire(name, required=True)
        except SecretStoreError as exc:
            raise CredentialUnavailable(str(exc)) from exc
        if secret is None:
            raise CredentialUnavailable(f"credential {name!r} is unavailable")
        return SecretLease(secret.reveal())

    def acquire_github_publish_token(self, repository: str) -> SecretLease:
        requested = str(repository or "").strip().strip("/")
        if not self._publish_enabled:
            raise CredentialUnavailable("GitHub branch publication credential broker is disabled")
        if not self._authorized(requested, self._publish_repository):
            raise CredentialUnavailable("GitHub publication repository is not authorized by the broker")
        return self._acquire("executor_github_publish_token")

    def acquire_github_pr_token(self, repository: str) -> SecretLease:
        requested = str(repository or "").strip().strip("/")
        if not self._pr_enabled:
            raise CredentialUnavailable("GitHub pull request credential broker is disabled")
        if not self._authorized(requested, self._pr_repository):
            raise CredentialUnavailable("GitHub pull request repository is not authorized by the broker")
        return self._acquire("executor_github_write_token")


class SettingsCredentialBroker(SecretStoreCredentialBroker):
    """Backward-compatible M8 broker using values already present in Settings."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, store=SettingsSecretStore(settings))
