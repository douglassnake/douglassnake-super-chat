#!/usr/bin/env python3
"""M14.3: local, deduplicated health alerts without external services."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts import ops_health_check as health
except ModuleNotFoundError:
    import ops_health_check as health  # Direct invocation from scripts/ on ZimaOS

DEFAULT_STATE_FILE = Path("/DATA/AppData/superchat/private/m14-3/health-state.json")
LOGGER_TAG = "superchat-ops-health"
ALERT_STATUSES = {"failed", "degraded"}


class AlertError(Exception):
    """An operational error without sensitive details."""


def _snapshot(report: dict) -> dict:
    """Stable, allowlisted metadata only: never include paths or log text."""
    return {
        "status": report["status"],
        "backup_state": report["backup"]["state"],
        "backup_reason": report["backup"].get("reason"),
        "restore_state": report["restore"]["state"],
        "restore_reason": report["restore"].get("reason"),
        "app_storage_state": report["storage"]["app"]["state"],
        "backup_storage_state": report["storage"]["backup"]["state"],
    }


def _fingerprint(snapshot: dict) -> str:
    data = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _read_state(path: Path) -> dict | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise AlertError("unsafe_state_file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a mapping")
        if data.get("version") != 1 or data.get("status") not in {"healthy", "degraded", "failed"}:
            raise ValueError("unknown schema")
        fingerprint = data.get("fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("invalid fingerprint")
        last_emit = data.get("last_emit_utc")
        if last_emit is not None:
            health.parse_aware(last_emit)
        return data
    except (OSError, ValueError, TypeError):
        raise AlertError("invalid_state_file") from None


def _decision(current: dict, previous: dict | None, now: datetime, remind_hours: float) -> str:
    status = current["status"]
    if previous is None:
        return "alert" if status in ALERT_STATUSES else "none"
    if current["fingerprint"] != previous["fingerprint"]:
        return "recovery" if status == "healthy" and previous["status"] != "healthy" else (
            "alert" if status in ALERT_STATUSES else "none"
        )
    if status not in ALERT_STATUSES:
        return "none"
    last_emit = previous.get("last_emit_utc")
    if last_emit is None:
        return "alert"
    last_time = health.parse_aware(last_emit)
    if now - last_time >= timedelta(hours=remind_hours):
        return "reminder"
    return "suppressed"


def _emit_local_event(kind: str, snapshot: dict, timestamp: str) -> None:
    """Write only allowlisted states/reasons to syslog via stdin, not argv."""
    logger = shutil.which("logger")
    if not logger:
        raise AlertError("logger_unavailable")
    priority = "user.info" if kind == "recovery" else "user.warning"
    if snapshot["status"] == "failed":
        priority = "user.err"
    event = {
        "event": "superchat.ops.health",
        "kind": kind,
        "checked_at_utc": timestamp,
        **snapshot,
    }
    try:
        subprocess.run(
            [logger, "-t", LOGGER_TAG, "-p", priority],
            input=json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n",
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise AlertError("logger_delivery_failed") from None


def _check_state_dir(path: Path) -> None:
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise AlertError("unsafe_state_directory")
    mode = stat.S_IMODE(parent.stat().st_mode)
    if mode & 0o077:
        raise AlertError("state_directory_permissions_too_open")


def _write_state(path: Path, document: dict) -> None:
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".health-state-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = stream.name
            os.chmod(temporary_path, 0o600)
            json.dump(document, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except OSError:
        raise AlertError("state_write_failed") from None
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def run_once(args: argparse.Namespace) -> dict:
    report = health.evaluate(args)
    snapshot = _snapshot(report)
    fingerprint = _fingerprint(snapshot)
    current = {"status": snapshot["status"], "fingerprint": fingerprint}
    now = health.parse_aware(report["checked_at_utc"])

    if args.dry_run:
        # Reading an existing state is fine; no directory creation, lock, logger or write.
        previous = _read_state(args.state_file)
        action = _decision(current, previous, now, args.remind_hours)
        return {
            "status": snapshot["status"], "snapshot": snapshot,
            "action": f"would_{action}", "dry_run": True,
        }

    args.state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_state_dir(args.state_file)
    lock_path = args.state_file.with_name(args.state_file.name + ".lock")
    if lock_path.is_symlink():
        raise AlertError("unsafe_lock_file")
    try:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise AlertError("lock_open_failed") from None
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise AlertError("concurrent_execution") from None
        previous = _read_state(args.state_file)
        action = _decision(current, previous, now, args.remind_hours)
        if action in {"alert", "recovery", "reminder"}:
            _emit_local_event(action, snapshot, report["checked_at_utc"])
            last_emit = report["checked_at_utc"]
        else:
            last_emit = previous.get("last_emit_utc") if previous is not None else None
        _write_state(args.state_file, {
            "version": 1, **current, "last_emit_utc": last_emit,
        })
        return {
            "status": snapshot["status"], "snapshot": snapshot,
            "action": action, "dry_run": False,
        }
    finally:
        os.close(lock_fd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-root", type=Path, default=Path("/DATA/Backup/superchat/automatic"))
    parser.add_argument("--app-root", type=Path, default=Path("/DATA/AppData/superchat"))
    parser.add_argument("--restore-log", type=Path, default=None)
    parser.add_argument("--restore-first-due", type=str, default=None)
    parser.add_argument("--backup-max-age-hours", type=float, default=36)
    parser.add_argument("--restore-max-age-hours", type=float, default=192)
    parser.add_argument("--restore-grace-hours", type=float, default=2)
    parser.add_argument("--min-free-percent", type=float, default=15)
    parser.add_argument("--remind-hours", type=float, default=24)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--dry-run", action="store_true", help="No logger or local state write")
    # M14.2 evaluate() expects args.now; real operations use the UTC clock.
    parser.set_defaults(now=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.restore_log is None:
        args.restore_log = args.backup_root / "restore-check.log"
    if (
        args.remind_hours <= 0 or args.backup_max_age_hours <= 0
        or args.restore_max_age_hours <= 0 or args.restore_grace_hours <= 0
        or not 0 < args.min_free_percent < 100
    ):
        parser.error("thresholds must be positive; min-free-percent must be between 0 and 100")

    try:
        response = run_once(args)
    except (AlertError, ValueError, OSError, KeyError, TypeError) as error:
        # Explicit allowlist avoids printing sensitive exception arguments.
        reason = error.args[0] if isinstance(error, AlertError) else "probe_execution_failed"
        print(json.dumps({"status": "error", "reason": reason}, sort_keys=True))
        return 3
    print(json.dumps(response, sort_keys=True, ensure_ascii=True))
    if response["status"] == "failed":
        return 1
    if response["status"] == "degraded":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
