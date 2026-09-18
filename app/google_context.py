from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context_engine import (
    PROFILE_CONFIG,
    Candidate,
    build_context_package,
    compact_candidate,
    deduplicate,
    score_candidate,
    timestamp_rank,
)
from app.google_sync import GoogleReader, drive_context_candidates
from app.models import ContextRun, Project


def build_context_with_google(
    db: Session,
    project: Project,
    query: str,
    profile: str = "standard",
    reader: GoogleReader | None = None,
) -> dict:
    """Build local context first, then fill remaining budget with Drive excerpts.

    Google is optional: missing OAuth or a failed Drive request never prevents the
    local memory package from being returned.
    """
    package = build_context_package(db, project, query, profile)
    candidates, _warnings = drive_context_candidates(
        db,
        project,
        query,
        profile,
        reader=reader,
    )
    if not candidates:
        return package

    now = datetime.now(timezone.utc)
    scored = [score_candidate(candidate, query, now) for candidate in candidates]
    unique = deduplicate(scored)
    unique.sort(
        key=lambda item: (item.score, item.importance, timestamp_rank(item.timestamp)),
        reverse=True,
    )

    budget = package["budget"]
    config = PROFILE_CONFIG[profile]
    remaining = int(budget["remaining_tokens"])
    max_items = max(0, int(config["max_items"]) - int(budget["selected_count"]))
    selected: list[Candidate] = []

    for candidate in unique:
        if len(selected) >= max_items or remaining <= 0:
            break
        item = candidate
        if item.estimated_tokens > remaining:
            item = compact_candidate(item, remaining)
            if item is None:
                continue
        if item.estimated_tokens <= remaining:
            selected.append(item)
            remaining -= item.estimated_tokens

    if not selected:
        budget["candidate_count"] += len(unique)
        budget["candidate_tokens"] += sum(item.estimated_tokens for item in unique)
        _update_audit(db, project, package)
        return package

    for item in selected:
        package["items"].append(
            {
                "kind": item.kind,
                "title": item.title,
                "content": item.content,
                "source_type": item.source_type,
                "source_ref": item.source_ref,
                "score": item.score,
                "estimated_tokens": item.estimated_tokens,
            }
        )
        source = {"source_type": item.source_type, "source_ref": item.source_ref}
        if source not in package["sources"]:
            package["sources"].append(source)

    added_tokens = sum(item.estimated_tokens for item in selected)
    budget["candidate_count"] += len(unique)
    budget["candidate_tokens"] += sum(item.estimated_tokens for item in unique)
    budget["selected_count"] += len(selected)
    budget["estimated_tokens"] += added_tokens
    budget["remaining_tokens"] = max(0, int(budget["max_tokens"]) - int(budget["estimated_tokens"]))

    _update_audit(db, project, package)
    return package


def _update_audit(db: Session, project: Project, package: dict) -> None:
    audit = db.scalar(
        select(ContextRun)
        .where(ContextRun.project_id == project.id)
        .order_by(ContextRun.created_at.desc())
        .limit(1)
    )
    if audit is None:
        return
    budget = package["budget"]
    audit.candidate_count = int(budget["candidate_count"])
    audit.selected_count = int(budget["selected_count"])
    audit.estimated_candidate_tokens = int(budget["candidate_tokens"])
    audit.estimated_selected_tokens = int(budget["estimated_tokens"])
    db.commit()
