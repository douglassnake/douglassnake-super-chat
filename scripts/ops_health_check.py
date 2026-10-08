#!/usr/bin/env python3
"""M14.2: read-only operational health/freshness probe for the ZimaOS host."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

DUMP_NAME = re.compile(r"^auto-superchat-(\d{8}T\d{6}Z)\.dump$")
SIDECAR = re.compile(r"^([a-fA-F0-9]{64})  (auto-superchat-\d{8}T\d{6}Z\.dump)$")
FATAL = {"missing", "invalid", "stale", "failed", "low_space", "missing_path"}
MAX_CLOCK_SKEW = timedelta(minutes=5)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def age_hours(now: datetime, then: datetime) -> float:
    return round(max((now - then).total_seconds(), 0) / 3600, 2)


def check_backup(root: Path, now: datetime, max_age_hours: float) -> dict:
    if not root.is_dir():
        return {"state": "missing", "reason": "backup_directory_missing"}

    candidates = []
    for entry in root.glob("auto-superchat-*.dump"):
        match = DUMP_NAME.fullmatch(entry.name)
        if match:
            candidates.append((match.group(1), entry))
    if not candidates:
        return {"state": "missing", "reason": "no_automatic_dump"}

    timestamp, selected = max(candidates, key=lambda item: item[0])
    result = {"name": selected.name}
    try:
        valid_file = not selected.is_symlink() and selected.is_file() and selected.stat().st_size > 0
    except OSError:
        valid_file = False
    if not valid_file:
        return {**result, "state": "invalid", "reason": "not_regular_nonempty_dump"}

    sidecar = Path(str(selected) + ".sha256")
    if sidecar.is_symlink() or not sidecar.is_file():
        return {**result, "state": "invalid", "reason": "missing_checksum"}
    try:
        content = sidecar.read_text(encoding="ascii").strip()
        match = SIDECAR.fullmatch(content)
        if match is None or match.group(2) != selected.name:
            return {**result, "state": "invalid", "reason": "invalid_checksum_metadata"}

        digest = hashlib.sha256()
        with selected.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest(), match.group(1).lower()):
            return {**result, "state": "invalid", "reason": "checksum_mismatch"}
    except (OSError, UnicodeError):
        return {**result, "state": "invalid", "reason": "backup_unreadable"}

    try:
        dump_time = datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return {**result, "state": "invalid", "reason": "invalid_filename_timestamp"}
    if dump_time - now > MAX_CLOCK_SKEW:
        return {**result, "state": "invalid", "reason": "future_dated_backup"}

    duration = age_hours(now, dump_time)
    return {
        **result,
        "state": "stale" if duration > max_age_hours else "fresh",
        "age_hours": duration,
        "max_age_hours": max_age_hours,
        "sha256_valid": True,
    }


def _restore_events(path: Path) -> tuple[list[datetime], list[datetime], list[datetime]]:
    completed: list[datetime] = []
    errors: list[datetime] = []
    started: list[datetime] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            prefix, _, event = line.partition(" ")
            try:
                when = parse_aware(prefix)
            except ValueError:
                continue
            if "restore-check: completed successfully" in event:
                completed.append(when)
            elif "ERROR:" in event:
                errors.append(when)
            elif "restore-check: validating SHA-256" in event:
                started.append(when)
    return completed, errors, started


def check_restore(
    log_path: Path,
    now: datetime,
    max_age_hours: float,
    first_due: datetime | None,
    grace_hours: float,
) -> dict:
    if log_path.is_symlink():
        return {"state": "failed", "reason": "restore_log_symlink"}
    if not log_path.exists():
        completed, errors, started = [], [], []
    else:
        if not log_path.is_file():
            return {"state": "failed", "reason": "restore_log_not_regular"}
        try:
            completed, errors, started = _restore_events(log_path)
        except OSError:
            return {"state": "failed", "reason": "restore_log_unreadable"}

    latest_ok = max(completed, default=None)
    latest_error = max(errors, default=None)
    latest_start = max(started, default=None)
    if latest_error is not None and (latest_ok is None or latest_error > latest_ok):
        return {"state": "failed", "reason": "restore_error_after_latest_success"}

    if latest_start is not None and (latest_ok is None or latest_start > latest_ok):
        if now - latest_start > timedelta(hours=grace_hours):
            return {"state": "failed", "reason": "restore_started_without_completion"}
        return {"state": "pending", "reason": "restore_in_progress_or_recently_started"}

    if latest_ok is None:
        if first_due is None:
            return {"state": "unknown", "reason": "no_success_log_or_initial_due_date"}
        if now < first_due + timedelta(hours=grace_hours):
            return {"state": "not_due", "first_due_utc": iso_utc(first_due)}
        return {"state": "failed", "reason": "first_scheduled_restore_not_confirmed"}

    if latest_ok - now > MAX_CLOCK_SKEW:
        return {"state": "failed", "reason": "future_dated_restore_log"}
    duration = age_hours(now, latest_ok)
    return {
        "state": "stale" if duration > max_age_hours else "fresh",
        "last_success_utc": iso_utc(latest_ok),
        "age_hours": duration,
        "max_age_hours": max_age_hours,
    }


def check_storage(app_root: Path, backup_root: Path, min_free_percent: float) -> dict:
    volumes = {}
    for label, path in (("app", app_root), ("backup", backup_root)):
        if not path.is_dir():
            volumes[label] = {"state": "missing_path"}
            continue
        try:
            usage = shutil.disk_usage(path)
            free_percent = round(100 * usage.free / usage.total, 2) if usage.total else 0.0
        except OSError:
            volumes[label] = {"state": "failed", "reason": "disk_usage_unavailable"}
            continue
        volumes[label] = {
            "state": "low_space" if free_percent < min_free_percent else "healthy",
            "free_percent": free_percent,
        }
    return volumes


def evaluate(args: argparse.Namespace) -> dict:
    now = parse_aware(args.now) if args.now else datetime.now(timezone.utc)
    first_due = parse_aware(args.restore_first_due) if args.restore_first_due else None

    backup = check_backup(args.backup_root, now, args.backup_max_age_hours)
    restore = check_restore(
        args.restore_log, now, args.restore_max_age_hours,
        first_due, args.restore_grace_hours,
    )
    storage = check_storage(args.app_root, args.backup_root, args.min_free_percent)
    states = [backup["state"], restore["state"]] + [v["state"] for v in storage.values()]
    status = (
        "failed" if any(item in FATAL for item in states)
        else "degraded" if any(item in {"unknown", "pending"} for item in states)
        else "healthy"
    )
    return {
        "status": status,
        "checked_at_utc": iso_utc(now),
        "backup": backup,
        "restore": restore,
        "storage": storage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-root", type=Path, default=Path("/DATA/Backup/superchat/automatic"))
    parser.add_argument("--app-root", type=Path, default=Path("/DATA/AppData/superchat"))
    parser.add_argument("--restore-log", type=Path, default=None)
    parser.add_argument("--backup-max-age-hours", type=float, default=36.0)
    parser.add_argument("--restore-max-age-hours", type=float, default=192.0)
    parser.add_argument("--restore-grace-hours", type=float, default=2.0)
    parser.add_argument("--min-free-percent", type=float, default=15.0)
    parser.add_argument("--restore-first-due", type=str, default=None, help="Offset-aware ISO 8601 timestamp")
    parser.add_argument("--now", type=str, default=None, help="Fixture clock override; omit on real host")
    args = parser.parse_args()
    if args.restore_log is None:
        args.restore_log = args.backup_root / "restore-check.log"
    if (
        args.backup_max_age_hours <= 0 or args.restore_max_age_hours <= 0
        or args.restore_grace_hours <= 0 or not 0 < args.min_free_percent < 100
    ):
        parser.error("thresholds must be positive and min-free-percent must be between 0 and 100")

    try:
        result = evaluate(args)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
