from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from app.models import ProjectSource


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _aware(parsed)


def source_freshness(
    source: ProjectSource,
    *,
    now: datetime | None = None,
    stale_after_seconds: int | None = None,
) -> dict[str, Any]:
    now = _aware(now) or datetime.now(timezone.utc)
    metadata = dict(source.metadata_json or {})
    configured = stale_after_seconds
    if configured is None:
        configured = int(os.environ.get("SUPERCHAT_GITHUB_STALE_AFTER_SECONDS", "7200"))
    configured = max(60, configured)

    last_synced_at = _parse_iso(metadata.get("last_synced_at"))
    last_attempt_at = _parse_iso(metadata.get("last_sync_attempt_at"))
    last_status = str(metadata.get("last_sync_status") or "").strip().lower() or None
    last_error = metadata.get("last_sync_error")

    if not source.is_active:
        status = "inactive"
    elif source.source_type != "github":
        status = "unknown"
    elif last_status == "failure" and (
        last_attempt_at is not None
        and (last_synced_at is None or last_attempt_at >= last_synced_at)
    ):
        status = "failed"
    elif last_synced_at is None:
        status = "never"
    else:
        age_seconds = max(0, int((now - last_synced_at).total_seconds()))
        status = "stale" if age_seconds > configured else "fresh"

    age_seconds = (
        max(0, int((now - last_synced_at).total_seconds()))
        if last_synced_at is not None
        else None
    )

    return {
        "status": status,
        "last_synced_at": last_synced_at,
        "last_attempt_at": last_attempt_at,
        "age_seconds": age_seconds,
        "stale_after_seconds": configured,
        "last_error": last_error if status == "failed" else None,
    }


def source_health_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {key: 0 for key in ("fresh", "stale", "failed", "never", "inactive", "unknown")}
    for item in items:
        status = str(item.get("status") or "unknown")
        counts[status if status in counts else "unknown"] += 1

    if counts["failed"]:
        overall = "failed"
    elif counts["stale"]:
        overall = "stale"
    elif counts["never"]:
        overall = "never"
    elif counts["fresh"]:
        overall = "fresh"
    elif counts["inactive"] and sum(counts.values()) == counts["inactive"]:
        overall = "inactive"
    else:
        overall = "unknown"

    return {"overall": overall, "counts": counts}
