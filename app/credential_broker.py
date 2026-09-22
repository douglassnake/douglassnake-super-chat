from __future__ import annotations

from typing import Protocol

from app.core.config import Settings


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


class SettingsCredentialBroker:
    """Minimal M8.14 broker.

    The settings backend is intentionally replaceable. Future deployments can
    swap this for Vault/KMS/OIDC without changing ExecutorRequest/WorkerJob.
    """

    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(settings.executor_github_publish_enabled)
        self._repository = str(settings.executor_github_publish_repository or "").strip().strip("/")
        self._token = str(settings.executor_github_publish_token or "").strip()

    def acquire_github_publish_token(self, repository: str) -> SecretLease:
        requested = str(repository or "").strip().strip("/")
        if not self._enabled:
            raise CredentialUnavailable("GitHub branch publication credential broker is disabled")
        if not self._repository or requested.lower() != self._repository.lower():
            raise CredentialUnavailable("GitHub publication repository is not authorized by the broker")
        if not self._token:
            raise CredentialUnavailable("GitHub publication credential is unavailable")
        return SecretLease(self._token)
