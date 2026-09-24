from __future__ import annotations

from collections import namedtuple
import json
import os
from pathlib import Path
import subprocess

import pytest

import app.self_hosted_preflight as preflight
from app.self_hosted_preflight import (
    build_preflight_report,
    check_backup_separation,
    check_directory,
    check_free_space,
    check_secret_store,
)


DiskUsage = namedtuple("DiskUsage", "total used free")


def _mkdir(path: Path, mode: int = 0o750) -> Path:
    path.mkdir()
    path.chmod(mode)
    return path


def _write_secret(root: Path, name: str, value: str, mode: int = 0o640) -> Path:
    path = root / name
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _docker_ok(command) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, stdout="27.0.0\n", stderr="")


def test_preflight_ready_report_is_sanitized(tmp_path: Path, monkeypatch) -> None:
    secret_value = "super-secret-auth-hash"
    secret_dir = _mkdir(tmp_path / "secrets", 0o750)
    data_dir = _mkdir(tmp_path / "data")
    backup_dir = _mkdir(tmp_path / "backup")
    _write_secret(secret_dir, "auth_password_hash", secret_value)

    monkeypatch.setattr(preflight.shutil, "which", lambda name: f"/usr/bin/{name}")

    report = build_preflight_report(
        secret_dir=secret_dir,
        data_dir=data_dir,
        backup_dir=backup_dir,
        minimum_free_gib=0,
        bind_port=0,
        docker_runner=_docker_ok,
    )

    assert report.ready
    assert any(item.status == "warn" for item in report.checks)
    rendered = json.dumps(report.to_dict())
    assert secret_value not in rendered
    assert report.to_dict()["status"] == "ready"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission policy")
def test_secret_directory_rejects_unsafe_permissions(tmp_path: Path) -> None:
    secret_dir = _mkdir(tmp_path / "secrets", 0o757)
    _write_secret(secret_dir, "auth_password_hash", "hash")

    result = check_secret_store(secret_dir)

    assert result.status == "fail"
    assert "other users" in result.detail


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission policy")
def test_secret_file_rejects_world_readable_permissions(tmp_path: Path) -> None:
    secret_dir = _mkdir(tmp_path / "secrets", 0o750)
    _write_secret(secret_dir, "auth_password_hash", "hash", mode=0o644)

    result = check_secret_store(secret_dir)

    assert result.status == "fail"
    assert "other users" in result.detail


def test_free_space_failure_is_explicit(tmp_path: Path) -> None:
    data_dir = _mkdir(tmp_path / "data")

    result = check_free_space(
        data_dir,
        minimum_free_gib=5,
        disk_usage=lambda _: DiskUsage(10 * 1024**3, 9 * 1024**3, 1 * 1024**3),
    )

    assert result.status == "fail"
    assert "below required" in result.detail


def test_backup_directory_must_differ_from_data_directory(tmp_path: Path) -> None:
    data_dir = _mkdir(tmp_path / "data")

    result = check_backup_separation(data_dir, data_dir, require_separate_device=False)

    assert result.status == "fail"
    assert "must differ" in result.detail


def test_same_filesystem_is_warning_unless_strict(tmp_path: Path) -> None:
    data_dir = _mkdir(tmp_path / "data")
    backup_dir = _mkdir(tmp_path / "backup")

    relaxed = check_backup_separation(data_dir, backup_dir, require_separate_device=False)
    strict = check_backup_separation(data_dir, backup_dir, require_separate_device=True)

    assert relaxed.status == "warn"
    assert strict.status == "fail"


def test_non_writable_or_missing_directory_fails(tmp_path: Path) -> None:
    result = check_directory(
        "data_directory",
        tmp_path / "missing",
        require_writable=True,
    )
    assert result.status == "fail"
    assert result.detail == "path does not exist"


def test_missing_docker_blocks_preflight(tmp_path: Path, monkeypatch) -> None:
    secret_dir = _mkdir(tmp_path / "secrets", 0o750)
    data_dir = _mkdir(tmp_path / "data")
    backup_dir = _mkdir(tmp_path / "backup")
    _write_secret(secret_dir, "auth_password_hash", "hash")
    monkeypatch.setattr(preflight.shutil, "which", lambda _: None)

    report = build_preflight_report(
        secret_dir=secret_dir,
        data_dir=data_dir,
        backup_dir=backup_dir,
        minimum_free_gib=0,
        bind_port=0,
    )

    assert not report.ready
    docker = next(item for item in report.checks if item.name == "docker_runtime")
    assert docker.status == "fail"
