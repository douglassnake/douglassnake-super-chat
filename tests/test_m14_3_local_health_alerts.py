"""M14.3: local-only, deduplicated alerts, no external delivery."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ops_health_alert as alert

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "ops_health_alert.py").read_text(encoding="utf-8")


def args(tmp_path: Path, dry_run: bool = False, **overrides):
    d = {
        "state_file": tmp_path / "private" / "health-state.json",
        "dry_run": dry_run,
        "remind_hours": 24,
    }
    d.update(overrides)
    return SimpleNamespace(**d)


def report(
    status: str = "healthy",
    *,
    when: str = "2026-10-08T13:53:19Z",
    backup: str = "fresh",
    restore: str = "not_due",
    app: str = "healthy",
    disk_backup: str = "healthy",
) -> dict:
    return {
        "checked_at_utc": when,
        "status": status,
        "backup": {"state": backup},
        "restore": {"state": restore},
        "storage": {"app": {"state": app}, "backup": {"state": disk_backup}},
    }


def setup_probe(monkeypatch, events: list[dict], result: dict):
    monkeypatch.setattr(alert.health, "evaluate", lambda _: result)
    monkeypatch.setattr(alert, "_emit_local_event", lambda kind, snap, timestamp:
                        events.append({"kind": kind, "snapshot": snap, "timestamp": timestamp}))


def test_initial_healthy_does_not_create_alert(tmp_path: Path, monkeypatch):
    events: list[dict] = []
    setup_probe(monkeypatch, events, report())
    result = alert.run_once(args(tmp_path))
    assert result["action"] == "none"
    assert result["status"] == "healthy"
    assert events == []
    state = json.loads((tmp_path / "private" / "health-state.json").read_text())
    assert state["status"] == "healthy"
    assert state["last_emit_utc"] is None
    assert os.stat(tmp_path / "private").st_mode & 0o077 == 0
    assert os.stat(tmp_path / "private" / "health-state.json").st_mode & 0o077 == 0


def test_failed_state_emits_only_once_before_reminder(tmp_path: Path, monkeypatch):
    events: list[dict] = []
    setup_probe(monkeypatch, events, report("failed", backup="stale"))
    first = alert.run_once(args(tmp_path))
    second = alert.run_once(args(tmp_path))
    assert first["action"] == "alert"
    assert second["action"] == "suppressed"
    assert len(events) == 1
    assert events[0]["snapshot"]["backup_state"] == "stale"


def test_reminder_after_24_hours_and_recovery(tmp_path: Path, monkeypatch):
    events: list[dict] = []
    setup_probe(monkeypatch, events, report("failed", backup="invalid"))
    assert alert.run_once(args(tmp_path))["action"] == "alert"
    setup_probe(monkeypatch, events, report("failed", backup="invalid", when="2026-10-09T14:54:00Z"))
    assert alert.run_once(args(tmp_path))["action"] == "reminder"
    setup_probe(monkeypatch, events, report("healthy", backup="fresh", restore="fresh", when="2026-10-09T15:10:00Z"))
    assert alert.run_once(args(tmp_path))["action"] == "recovery"
    assert [item["kind"] for item in events] == ["alert", "reminder", "recovery"]
    assert alert.run_once(args(tmp_path))["action"] == "none"
    assert len(events) == 3


def test_degraded_is_alert_not_success(tmp_path: Path, monkeypatch):
    events: list[dict] = []
    setup_probe(monkeypatch, events, report("degraded", restore="unknown"))
    first = alert.run_once(args(tmp_path))
    assert first["action"] == "alert"
    assert first["status"] == "degraded"
    assert len(events) == 1
    assert events[0]["snapshot"]["restore_state"] == "unknown"


def test_changes_to_failing_reason_emit_new_event(tmp_path: Path, monkeypatch):
    events: list[dict] = []
    setup_probe(monkeypatch, events, report("failed", backup="missing"))
    assert alert.run_once(args(tmp_path))["action"] == "alert"
    setup_probe(monkeypatch, events, report("failed", backup="invalid"))
    assert alert.run_once(args(tmp_path))["action"] == "alert"
    assert len(events) == 2


def test_dry_run_never_creates_state_directory_or_journal(tmp_path: Path, monkeypatch):
    events: list[dict] = []
    setup_probe(monkeypatch, events, report("failed", backup="missing"))
    result = alert.run_once(args(tmp_path, dry_run=True))
    assert result["action"] == "would_alert"
    assert result["dry_run"] is True
    assert not (tmp_path / "private").exists()
    assert events == []


def test_failed_logger_does_not_silently_advance_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(alert.health, "evaluate", lambda _: report("failed", backup="stale"))
    def fail(*unused):
        raise alert.AlertError("logger_delivery_failed")
    monkeypatch.setattr(alert, "_emit_local_event", fail)
    with pytest.raises(alert.AlertError, match="logger_delivery_failed"):
        alert.run_once(args(tmp_path))
    assert not (tmp_path / "private" / "health-state.json").exists()


def test_corrupt_state_file_is_fail_closed(tmp_path: Path, monkeypatch):
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    (folder / "health-state.json").write_text('{"invalid": true}')
    events: list[dict] = []
    setup_probe(monkeypatch, events, report("failed", backup="stale"))
    with pytest.raises(alert.AlertError, match="invalid_state_file"):
        alert.run_once(args(tmp_path))
    assert events == []


def test_alert_message_contains_only_allowlisted_data(monkeypatch):
    output = []
    monkeypatch.setattr(alert.shutil, "which", lambda n: "/usr/bin/logger" if n == "logger" else None)
    monkeypatch.setattr(alert.subprocess, "run", lambda cmd, **kwargs: output.append((cmd, kwargs)))
    alert._emit_local_event("alert", alert._snapshot(report("failed", backup="missing")),
                            "2026-10-08T13:53:19Z")
    cmd, kwargs = output[0]
    assert cmd[:3] == ["/usr/bin/logger", "-t", "superchat-ops-health"]
    assert "-p" in cmd
    assert "user.err" in cmd
    body = json.loads(kwargs["input"])
    assert body["event"] == "superchat.ops.health"
    assert body["status"] == "failed"
    assert not any(key in kwargs["input"] for key in ("DATABASE_URL", "password", "token", "/DATA/", "dump"))


def test_main_exit_codes_differentiate_healthy_failed_and_degraded(tmp_path: Path, monkeypatch, capsys):
    cases = [("healthy", 0), ("failed", 1), ("degraded", 2)]
    monkeypatch.setattr(alert, "run_once", lambda _: {"status": current[0], "action": "none"})
    for current in cases:
        monkeypatch.setattr(
            "sys.argv", ["ops_health_alert.py", "--dry-run", "--state-file", str(tmp_path / "none")]
        )
        assert alert.main() == current[1]
        assert json.loads(capsys.readouterr().out)["status"] == current[0]



def test_real_cli_dry_run_uses_health_probe_without_missing_now(tmp_path: Path):
    """Regression: actual CLI -> M14.2 evaluate() without mocks or logger."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    name = f"auto-superchat-{stamp}.dump"
    dump = backup_dir / name
    dump.write_bytes(b"synthetic integration fixture - never production")
    checksum = hashlib.sha256(dump.read_bytes()).hexdigest()
    (backup_dir / (name + ".sha256")).write_text(
        f"{checksum}  {name}\\n", encoding="ascii",
    )
    state_file = tmp_path / "private" / "health-state.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ops_health_alert.py"),
            "--backup-root", str(backup_dir),
            "--app-root", str(tmp_path),
            "--restore-first-due", "2099-01-01T00:00:00+00:00",
            "--state-file", str(state_file),
            "--dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "healthy"
    assert payload["snapshot"]["backup_state"] == "fresh"
    assert payload["snapshot"]["restore_state"] == "not_due"
    assert payload["action"] == "would_none"
    assert payload["dry_run"] is True
    assert not state_file.exists()
    assert not state_file.parent.exists()


def test_script_never_manages_docker_database_or_cron():
    for forbidden in (
        "docker restart", "docker compose", "docker exec",
        "dropdb", "createdb", "crontab -", "docker prune",
        "DATABASE_URL", "POSTGRES_PASSWORD", "curl ",
    ):
        assert forbidden not in SRC
