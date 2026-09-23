from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Protocol

from app.core.config import Settings

ALLOWED_SECRET_NAMES = frozenset(
    {
        "auth_password_hash",
        "github_token",
        "google_access_token",
        "google_client_secret",
        "google_refresh_token",
        "executor_github_write_token",
        "executor_github_publish_token",
    }
)
MAX_SECRET_BYTES = 16_384


class SecretStoreError(RuntimeError):
    pass


class SecretValue:
    __slots__ = ("_value", "name")

    def __init__(self, name: str, value: str) -> None:
        if name not in ALLOWED_SECRET_NAMES:
            raise SecretStoreError("secret name is not allowed")
        cleaned = str(value or "").strip()
        if not cleaned:
            raise SecretStoreError(f"secret {name!r} is empty")
        self.name = name
        self._value = cleaned

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"<SecretValue {self.name} [REDACTED]>"

    def __str__(self) -> str:
        return "[REDACTED]"


class SecretStore(Protocol):
    def acquire(self, name: str, *, required: bool = False) -> SecretValue | None: ...


class SettingsSecretStore:
    """Compatibility backend for development/private local installations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def acquire(self, name: str, *, required: bool = False) -> SecretValue | None:
        if name not in ALLOWED_SECRET_NAMES:
            raise SecretStoreError("secret name is not allowed")
        value = str(getattr(self.settings, name, None) or "").strip()
        if not value:
            if required:
                raise SecretStoreError(f"secret {name!r} is unavailable")
            return None
        return SecretValue(name, value)


class FileSecretStore:
    """Read secrets from a private mounted directory on every acquisition.

    Re-reading avoids long-lived caching and lets an operator rotate a secret by
    atomically replacing its file. The backend never writes secret material.
    """

    def __init__(self, root: str | Path) -> None:
        raw = Path(root).expanduser()
        if not raw.is_absolute():
            raise SecretStoreError("SECRET_DIR must be an absolute path")
        try:
            info = raw.lstat()
        except FileNotFoundError as exc:
            raise SecretStoreError("SECRET_DIR does not exist") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SecretStoreError("SECRET_DIR must be a real directory, not a symlink")
        self.root = raw

    def _path(self, name: str) -> Path:
        if name not in ALLOWED_SECRET_NAMES:
            raise SecretStoreError("secret name is not allowed")
        return self.root / name

    @staticmethod
    def _validate_file(path: Path) -> os.stat_result:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise SecretStoreError(f"secret file {path.name!r} does not exist") from exc
        if stat.S_ISLNK(info.st_mode):
            raise SecretStoreError(f"secret file {path.name!r} must not be a symlink")
        if not stat.S_ISREG(info.st_mode):
            raise SecretStoreError(f"secret file {path.name!r} must be a regular file")
        if info.st_size <= 0 or info.st_size > MAX_SECRET_BYTES:
            raise SecretStoreError(f"secret file {path.name!r} has an invalid size")
        if os.name == "posix" and (stat.S_IMODE(info.st_mode) & 0o007):
            raise SecretStoreError(
                f"secret file {path.name!r} must not grant permissions to other users"
            )
        return info

    def acquire(self, name: str, *, required: bool = False) -> SecretValue | None:
        path = self._path(name)
        if not path.exists():
            if required:
                raise SecretStoreError(f"secret {name!r} is unavailable")
            return None
        before = self._validate_file(path)
        try:
            with path.open("rb") as handle:
                payload = handle.read(MAX_SECRET_BYTES + 1)
                after_fd = os.fstat(handle.fileno())
        except OSError as exc:
            raise SecretStoreError(f"secret file {name!r} cannot be read") from exc
        if len(payload) > MAX_SECRET_BYTES:
            raise SecretStoreError(f"secret file {name!r} exceeds the size limit")
        if (before.st_dev, before.st_ino) != (after_fd.st_dev, after_fd.st_ino):
            raise SecretStoreError(f"secret file {name!r} changed during acquisition")
        if b"\x00" in payload:
            raise SecretStoreError(f"secret file {name!r} contains invalid NUL bytes")
        try:
            value = payload.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise SecretStoreError(f"secret file {name!r} must be UTF-8") from exc
        if not value:
            if required:
                raise SecretStoreError(f"secret {name!r} is empty")
            return None
        return SecretValue(name, value)


def build_secret_store(settings: Settings) -> SecretStore:
    backend = str(settings.secret_backend or "settings").strip().lower()
    if backend == "settings":
        return SettingsSecretStore(settings)
    if backend == "files":
        if not settings.secret_dir:
            raise SecretStoreError("SECRET_DIR is required when SECRET_BACKEND=files")
        return FileSecretStore(settings.secret_dir)
    raise SecretStoreError("SECRET_BACKEND must be 'settings' or 'files'")


def resolve_secret(settings: Settings, name: str, *, required: bool = False) -> str | None:
    lease = build_secret_store(settings).acquire(name, required=required)
    return lease.reveal() if lease is not None else None
