"""M14.2: deterministic tests for the read-only ZimaOS health probe."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ops_health_check as probe


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ops_health_check.py"
NOW = datetime(2026, 10, 8, 13, 31, tzinfo=timezone.utc)


def backup(root: Path, when: datetime = NOW - timedelta(hours=8), valid: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    name = "auto-superchat-" + when.strftime("%Y%m%dT%H%M%SZ") + ".dump"
    dump = root / name
    dump.write_bytes(b"fixture: not a real PostgreSQL dump")
    digest = hashlib.sha256(dump.read_bytes()).hexdigest() if valid else "0" * 64
    Path(str(dump) + ".sha256").write_text(f"{digest}  {name}\n", encoding="ascii")
    return dump


def args(root: Path, log: Path, **overrides):
    values = {
        "backup_root": root, "app_root": root, "restore_log": log,
        "backup_max_age_hours": 36.0, "restore_max_age_hours": 192.0,
        "restore_grace_hours": 2.0, "min_free_percent": 15.0,
        "restore_first_due": "2026-10-11T04:00:00-03:00",
        "now": NOW.isoformat(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fresh_backup_and_not_due_restore_is_healthy(tmp_path: Path):
    backup(tmp_path)
    result = probe.evaluate(args(tmp_path, tmp_path / "restore-check.log"))
    assert result["status"] == "healthy"
    assert result["backup"]["state"] == "fresh"
    assert result["backup"]["sha256_valid"]
    assert result["restore"]["state"] == "not_due"
    assert result["storage"]["app"]["state"] == "healthy"


def test_checksum_mismatch_fails(tmp_path: Path):
    backup(tmp_path, valid=False)
    result = probe.evaluate(args(tmp_path, tmp_path / "restore-check.log"))
    assert result["backup"]["state"] == "invalid"
    assert result["backup"]["reason"] == "checksum_mismatch"
    assert result["status"] == "failed"


def test_missing_and_stale_backup_fail(tmp_path: Path):
    assert probe.check_backup(tmp_path, NOW, 36)["state"] == "missing"
    backup(tmp_path, NOW - timedelta(hours=48))
    result = probe.evaluate(args(tmp_path, tmp_path / "restore-check.log"))
    assert result["backup"]["state"] == "stale"
    assert result["backup"]["age_hours"] == 48
    assert result["status"] == "failed"


def test_future_dated_backup_is_invalid(tmp_path: Path):
    backup(tmp_path, NOW + timedelta(days=1))
    assert probe.check_backup(tmp_path, NOW, 36)["reason"] == "future_dated_backup"



def test_malformed_filename_timestamp_is_reported_not_crashed(tmp_path: Path):
    broken = tmp_path / "auto-superchat-20261399T061501Z.dump"
    broken.write_bytes(b"fixture")
    digest = hashlib.sha256(broken.read_bytes()).hexdigest()
    Path(str(broken) + ".sha256").write_text(
        f"{digest}  {broken.name}\n", encoding="ascii",
    )
    result = probe.check_backup(tmp_path, NOW, 36)
    assert result["state"] == "invalid"
    assert result["reason"] == "invalid_filename_timestamp"


def test_symlink_checksum_is_rejected(tmp_path: Path):
    dump = backup(tmp_path)
    sidecar = Path(str(dump) + ".sha256")
    actual = tmp_path / "outside"
    sidecar.rename(actual)
    try:
        sidecar.symlink_to(actual)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert probe.check_backup(tmp_path, NOW, 36)["reason"] == "missing_checksum"


def test_no_restore_log_without_initial_due_is_explicitly_unknown(tmp_path: Path):
    backup(tmp_path)
    result = probe.evaluate(args(tmp_path, tmp_path / "restore-check.log", restore_first_due=None))
    assert result["restore"]["state"] == "unknown"
    assert result["status"] == "degraded"


def test_missing_first_scheduled_restore_fails_after_grace(tmp_path: Path):
    backup(tmp_path, NOW)
    result = probe.evaluate(args(
        tmp_path, tmp_path / "restore-check.log",
        restore_first_due="2026-10-07T04:00:00-03:00",
    ))
    assert result["restore"]["reason"] == "first_scheduled_restore_not_confirmed"
    assert result["status"] == "failed"


def test_recent_success_and_expired_success(tmp_path: Path):
    log = tmp_path / "restore-check.log"
    log.write_text("2026-10-08T08:00:00Z restore-check: completed successfully\n")
    assert probe.check_restore(log, NOW, 192, None, 2)["state"] == "fresh"
    log.write_text("2026-09-28T08:00:00Z restore-check: completed successfully\n")
    assert probe.check_restore(log, NOW, 192, None, 2)["state"] == "stale"


def test_restore_error_after_success_fails_without_leaking_text(tmp_path: Path):
    log = tmp_path / "restore-check.log"
    log.write_text(
        "2026-10-07T08:00:00Z restore-check: completed successfully\n"
        "2026-10-08T08:00:00Z ERROR: sensitive private database error message\n"
    )
    result = probe.check_restore(log, NOW, 192, None, 2)
    assert result == {"state": "failed", "reason": "restore_error_after_latest_success"}
    assert "sensitive" not in json.dumps(result)


def test_interrupted_restore_without_completion_fails(tmp_path: Path):
    log = tmp_path / "restore-check.log"
    log.write_text("2026-10-08T09:00:00Z restore-check: validating SHA-256 for backup\n")
    assert probe.check_restore(log, NOW, 192, None, 2)["reason"] == "restore_started_without_completion"


def test_storage_low_space_is_detected_without_modifying_disk(tmp_path: Path, monkeypatch):
    usage = shutil_usage = SimpleNamespace(total=100, used=90, free=10)
    monkeypatch.setattr(probe.shutil, "disk_usage", lambda path: shutil_usage)
    result = probe.check_storage(tmp_path, tmp_path, min_free_percent=15)
    assert result["app"] == {"state": "low_space", "free_percent": 10.0}
    assert result["backup"]["state"] == "low_space"
    assert usage.used == 90


def test_cli_exit_codes_are_stable_and_output_is_json(tmp_path: Path):
    backup(tmp_path)
    command = [
        sys.executable, str(SCRIPT),
        "--backup-root", str(tmp_path),
        "--app-root", str(tmp_path),
        "--restore-log", str(tmp_path / "restore-check.log"),
        "--restore-first-due", "2026-10-11T04:00:00-03:00",
        "--now", NOW.isoformat(),
    ]
    ok = subprocess.run(command, text=True, capture_output=True, check=False)
    assert ok.returncode == 0
    assert json.loads(ok.stdout)["status"] == "healthy"
    assert "POSTGRES_PASSWORD" not in ok.stdout
    for file in tmp_path.glob("auto-superchat-*.dump"):
        file.unlink()
    for file in tmp_path.glob("*.sha256"):
        file.unlink()
    failure = subprocess.run(command, text=True, capture_output=True, check=False)
    assert failure.returncode == 1
    assert json.loads(failure.stdout)["backup"]["state"] == "missing"


def test_script_does_not_mutate_database_or_cron():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "docker restart", "docker compose", "docker exec",
        "dropdb", "createdb", "crontab -", "subprocess.call", "os.system",
    ):
        assert forbidden not in source
