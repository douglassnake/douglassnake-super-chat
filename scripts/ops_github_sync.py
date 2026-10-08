#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.github_sync import GitHubAPIError, record_github_sync_failure, sync_project_github
from app.models import Project, ProjectSource


DEFAULT_LOCK_FILE = "/tmp/superchat-github-sync.lock"


@dataclass(frozen=True)
class SyncTarget:
    project_id: UUID
    slug: str
    source_count: int


class SyncAlreadyRunning(RuntimeError):
    pass


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error(exc: Exception) -> dict[str, object]:
    if isinstance(exc, GitHubAPIError):
        payload: dict[str, object] = {"type": "GitHubAPIError"}
        if exc.status_code is not None:
            payload["status_code"] = exc.status_code
        return payload
    return {"type": type(exc).__name__}


@contextmanager
def exclusive_lock(path: str):
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    handle = os.fdopen(fd, "a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SyncAlreadyRunning("GitHub sync is already running") from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def discover_targets(
    session_factory: Callable[[], Session] = SessionLocal,
) -> list[SyncTarget]:
    with session_factory() as db:
        stmt = (
            select(
                Project.id,
                Project.slug,
                func.count(ProjectSource.id).label("source_count"),
            )
            .join(ProjectSource, ProjectSource.project_id == Project.id)
            .where(
                Project.status == "active",
                ProjectSource.source_type == "github",
                ProjectSource.is_active.is_(True),
            )
            .group_by(Project.id, Project.slug)
            .order_by(Project.slug)
        )
        return [
            SyncTarget(
                project_id=row.id,
                slug=row.slug,
                source_count=int(row.source_count),
            )
            for row in db.execute(stmt)
        ]


def build_check_report(
    session_factory: Callable[[], Session] = SessionLocal,
) -> dict[str, Any]:
    started = perf_counter()
    targets = discover_targets(session_factory)
    return {
        "mode": "check",
        "generated_at": _utc_iso(),
        "projects": [
            {
                "slug": target.slug,
                "status": "eligible",
                "source_count": target.source_count,
            }
            for target in targets
        ],
        "totals": {
            "eligible_projects": len(targets),
            "source_count": sum(target.source_count for target in targets),
        },
        "duration_ms": int((perf_counter() - started) * 1000),
    }


def sync_active_github_projects(
    session_factory: Callable[[], Session] = SessionLocal,
    sync_func: Callable[[Session, Project], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    targets = discover_targets(session_factory)
    run_sync = sync_func or sync_project_github

    reports: list[dict[str, Any]] = []
    total_created = 0
    total_skipped = 0
    total_sources = 0
    successful = 0
    failed = 0

    for target in targets:
        project_started = perf_counter()
        report: dict[str, Any] = {
            "slug": target.slug,
            "source_count": target.source_count,
        }

        try:
            with session_factory() as db:
                project = db.get(Project, target.project_id)
                if project is None:
                    raise LookupError("Project disappeared during synchronization")
                result = run_sync(db, project)

            created = int(result.get("created_events") or 0)
            skipped = int(result.get("skipped_events") or 0)
            source_count = int(result.get("source_count") or target.source_count)
            digest = result.get("digest") or {}

            report.update(
                {
                    "status": "success",
                    "source_count": source_count,
                    "created_events": created,
                    "skipped_events": skipped,
                    "digest": {
                        "created": bool(digest.get("created")),
                        "pending_exists": bool(digest.get("pending_exists")),
                        "event_count": int(digest.get("event_count") or 0),
                        "suggested_tasks": int(digest.get("suggested_tasks") or 0),
                    },
                }
            )
            total_created += created
            total_skipped += skipped
            total_sources += source_count
            successful += 1
        except Exception as exc:
            safe_error = _safe_error(exc)
            try:
                with session_factory() as failure_db:
                    record_github_sync_failure(
                        failure_db,
                        target.project_id,
                        safe_error,
                    )
            except Exception:
                pass
            report.update(
                {
                    "status": "failure",
                    "error": safe_error,
                }
            )
            total_sources += target.source_count
            failed += 1

        report["duration_ms"] = int((perf_counter() - project_started) * 1000)
        reports.append(report)

    return {
        "mode": "sync",
        "generated_at": _utc_iso(),
        "projects": reports,
        "totals": {
            "eligible_projects": len(targets),
            "successful_projects": successful,
            "failed_projects": failed,
            "source_count": total_sources,
            "created_events": total_created,
            "skipped_events": total_skipped,
        },
        "duration_ms": int((perf_counter() - started) * 1000),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize active GitHub project sources into the local Second Brain. "
            "External access is read-only; internal events/source metadata are updated idempotently."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only list eligible active projects/sources; do not call GitHub or write the database",
    )
    parser.add_argument(
        "--lock-file",
        default=os.environ.get("SUPERCHAT_GITHUB_SYNC_LOCK", DEFAULT_LOCK_FILE),
        help="advisory lock file used to prevent concurrent runs",
    )
    args = parser.parse_args(argv)

    try:
        with exclusive_lock(args.lock_file):
            report = build_check_report() if args.check else sync_active_github_projects()
    except SyncAlreadyRunning:
        print(
            json.dumps(
                {
                    "mode": "check" if args.check else "sync",
                    "status": "busy",
                },
                sort_keys=True,
            )
        )
        return 75
    except Exception as exc:
        print(
            json.dumps(
                {
                    "mode": "check" if args.check else "sync",
                    "status": "failure",
                    "error": _safe_error(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not args.check and int(report["totals"]["failed_projects"]) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
