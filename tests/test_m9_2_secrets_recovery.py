from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from app.core.config import Settings
from app.credential_broker import SecretStoreCredentialBroker
from app.recovery import RecoveryError, load_and_verify_manifest, sha256_file, _tool_command
from app.secret_store import FileSecretStore, SecretStoreError


def _write_secret(root: Path, name: str, value: str, *, mode: int = 0o640) -> Path:
    path = root / name
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(mode)
    return path


def test_file_secret_store_rotation_and_settings_redaction(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o700)
    _write_secret(secret_dir, "executor_github_publish_token", "publish-v1")
    _write_secret(secret_dir, "auth_password_hash", "pbkdf2_sha256$200000$abc$def")

    settings = Settings(
        _env_file=None,
        secret_backend="files",
        secret_dir=str(secret_dir),
        executor_github_publish_enabled=True,
        executor_github_publish_repository="owner/repo",
    )
    assert settings.executor_github_publish_token == "publish-v1"
    assert "executor_github_publish_token" not in settings.model_dump()
    assert "publish-v1" not in settings.model_dump_json()

    broker = SecretStoreCredentialBroker(settings)
    first = broker.acquire_github_publish_token("owner/repo")
    assert first.reveal() == "publish-v1"
    assert "publish-v1" not in repr(first)

    replacement = secret_dir / ".publish.new"
    replacement.write_text("publish-v2\n", encoding="utf-8")
    replacement.chmod(0o640)
    os.replace(replacement, secret_dir / "executor_github_publish_token")

    second = broker.acquire_github_publish_token("owner/repo")
    assert second.reveal() == "publish-v2"
    # Settings keeps only its startup snapshot; privileged effects use the broker
    # and therefore observe atomic file rotation without process restart.
    assert settings.executor_github_publish_token == "publish-v1"


def test_file_secret_store_rejects_unsafe_files(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o700)
    store = FileSecretStore(secret_dir)

    world_readable = _write_secret(secret_dir, "github_token", "unsafe", mode=0o644)
    if os.name == "posix":
        with pytest.raises(SecretStoreError, match="other users"):
            store.acquire("github_token", required=True)
    world_readable.unlink()

    target = _write_secret(secret_dir, "google_access_token", "target")
    link = secret_dir / "github_token"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(SecretStoreError, match="symlink"):
        store.acquire("github_token", required=True)


def test_secret_store_rejects_unknown_name_and_relative_root(tmp_path: Path) -> None:
    with pytest.raises(SecretStoreError, match="absolute"):
        FileSecretStore(Path("relative-secrets"))

    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    store = FileSecretStore(secret_dir)
    with pytest.raises(SecretStoreError, match="not allowed"):
        store.acquire("arbitrary_secret", required=True)


def test_backup_manifest_detects_tampering(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir(mode=0o700)
    dump = backup / "database.dump"
    dump.write_bytes(b"postgres-custom-dump-placeholder")
    dump.chmod(0o600)
    manifest = {
        "format_version": 1,
        "created_at": "2026-09-23T00:00:00+00:00",
        "dump_file": "database.dump",
        "sha256": sha256_file(dump),
        "bytes": dump.stat().st_size,
        "alembic_head": "0009_auth_sessions",
        "table_count": 10,
        "required_tables_present": [],
    }
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    loaded, loaded_dump = load_and_verify_manifest(backup)
    assert loaded["sha256"] == manifest["sha256"]
    assert loaded_dump == dump

    dump.write_bytes(b"tampered")
    with pytest.raises(RecoveryError, match="size|SHA-256"):
        load_and_verify_manifest(backup)


def test_database_password_is_not_put_in_pg_tool_argv(monkeypatch) -> None:
    monkeypatch.setattr("app.recovery.shutil.which", lambda name: f"/usr/bin/{name}")
    url = "postgresql+psycopg://user:SUPER_SECRET_PASSWORD@db.example:5432/superchat"
    command, env = _tool_command("pg_dump", url)
    rendered = " ".join(command)
    assert "SUPER_SECRET_PASSWORD" not in rendered
    assert env["PGPASSWORD"] == "SUPER_SECRET_PASSWORD"

    command, env = _tool_command("pg_dump", url, postgres_container="postgres-db")
    rendered = " ".join(command)
    assert "SUPER_SECRET_PASSWORD" not in rendered
    assert "-e PGPASSWORD" in rendered
    assert env["PGPASSWORD"] == "SUPER_SECRET_PASSWORD"
