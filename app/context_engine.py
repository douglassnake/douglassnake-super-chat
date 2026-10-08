from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import ContextItem, ContextRun, Decision, Event, Project, SessionSummary, Task


PROFILE_CONFIG = {
    "minimal": {
        "max_tokens": 1800,
        "max_items": 10,
        "summary_limit": 1,
        "event_limit": 20,
        "max_successful_workflow_runs": 1,
    },
    "standard": {
        "max_tokens": 5000,
        "max_items": 25,
        "summary_limit": 3,
        "event_limit": 60,
        "max_successful_workflow_runs": 3,
    },
    "deep": {
        "max_tokens": 15000,
        "max_items": 60,
        "summary_limit": 6,
        "event_limit": 150,
        "max_successful_workflow_runs": 8,
    },
}

TYPE_STRENGTH = {
    "summary": 1.00,
    "decision": 0.98,
    "deployment": 0.97,
    "architecture": 0.96,
    "task": 0.95,
    "operational": 0.94,
    "runbook": 0.94,
    "fact": 0.90,
    "document_excerpt": 0.85,
    "event": 0.82,
    "note": 0.70,
}

SOURCE_STRENGTH = {
    "github": 0.98,
    "drive": 0.90,
    "calendar": 0.90,
    "summary": 0.90,
    "decision": 0.90,
    "task": 0.90,
    "manual": 0.75,
    "local": 0.70,
}

_WORD_RE = re.compile(r"[\wÀ-ÿ-]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

_OPERATIONAL_QUERY_TERMS = (
    "continuar",
    "status",
    "próxima ação",
    "proxima acao",
    "decis",
    "decision",
    "tarefa",
    "task",
    "pend",
    "bloque",
    "next action",
    "implant",
    "deployment",
    "arquitet",
    "architecture",
    "backup",
    "restore",
)


@dataclass(frozen=True)
class Candidate:
    kind: str
    title: str | None
    content: str
    source_type: str
    source_ref: str | None
    timestamp: datetime | None
    importance: float
    event_type: str | None = None
    event_conclusion: str | None = None
    score: float = 0.0
    estimated_tokens: int = 0


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil((len(text) / 4.0) * 1.15))


def normalize_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip().lower())


def words(value: str) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(value) if len(token) > 1}


def lexical_relevance(query: str, text: str) -> float:
    query_words = words(query)
    if not query_words:
        return 0.0
    text_words = words(text)
    if not text_words:
        return 0.0
    return len(query_words & text_words) / len(query_words)


def recency_score(timestamp: datetime | None, now: datetime) -> float:
    if timestamp is None:
        return 0.25
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - timestamp).total_seconds() / 86400.0)
    return 1.0 / (1.0 + age_days / 30.0)


def timestamp_rank(timestamp: datetime | None) -> float:
    if timestamp is None:
        return 0.0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.timestamp()


def render_candidate(candidate: Candidate) -> str:
    parts = [candidate.kind]
    if candidate.title:
        parts.append(candidate.title)
    parts.append(candidate.content)
    if candidate.source_ref:
        parts.append(candidate.source_ref)
    return "\n".join(parts)


def has_operational_intent(query: str) -> bool:
    normalized = normalize_text(query)
    return any(term in normalized for term in _OPERATIONAL_QUERY_TERMS)


def intent_bonus(candidate: Candidate, query: str) -> float:
    normalized = normalize_text(query)
    bonus = 0.0

    if candidate.kind == "decision" and any(term in normalized for term in ("decis", "decision", "arquitet", "architecture")):
        bonus += 0.12

    if candidate.kind == "task" and any(
        term in normalized
        for term in ("tarefa", "task", "próxima ação", "proxima acao", "next action", "pend", "bloque", "backup", "restore")
    ):
        bonus += 0.10

    if candidate.kind in {"deployment", "architecture", "operational", "runbook"} and any(
        term in normalized
        for term in ("implant", "deployment", "arquitet", "architecture", "infra", "backup", "restore")
    ):
        bonus += 0.10

    return bonus


def score_candidate(candidate: Candidate, query: str, now: datetime) -> Candidate:
    text = render_candidate(candidate)
    relevance = lexical_relevance(query, text)
    recency = recency_score(candidate.timestamp, now)
    type_strength = TYPE_STRENGTH.get(candidate.kind, 0.65)
    source_strength = SOURCE_STRENGTH.get(candidate.source_type, 0.70)
    importance = min(1.0, max(0.0, candidate.importance))
    score = (
        relevance * 0.40
        + importance * 0.25
        + recency * 0.15
        + type_strength * 0.10
        + source_strength * 0.10
        + intent_bonus(candidate, query)
    )
    return replace(
        candidate,
        score=round(min(1.0, score), 6),
        estimated_tokens=estimate_tokens(text),
    )


def deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    best_by_content: dict[str, Candidate] = {}
    for candidate in candidates:
        key = normalize_text(candidate.content)
        if not key:
            continue
        current = best_by_content.get(key)
        if current is None or candidate.score > current.score:
            best_by_content[key] = candidate
    return list(best_by_content.values())


def compact_candidate(candidate: Candidate, token_limit: int) -> Candidate | None:
    if token_limit < 48:
        return None
    metadata_tokens = estimate_tokens("\n".join(filter(None, [candidate.kind, candidate.title, candidate.source_ref]))) + 6
    content_budget = token_limit - metadata_tokens
    if content_budget < 24:
        return None
    max_chars = max(80, int((content_budget * 4.0) / 1.15))
    if len(candidate.content) <= max_chars:
        return candidate
    compacted = replace(candidate, content=candidate.content[: max_chars - 1].rstrip() + "…")
    compacted = replace(compacted, estimated_tokens=estimate_tokens(render_candidate(compacted)))
    if compacted.estimated_tokens > token_limit:
        return None
    return compacted


def compact_project_text(value: str | None, max_chars: int = 1200) -> str | None:
    if value is None or len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _summary_candidates(db: Session, project_id: UUID, limit: int) -> list[Candidate]:
    stmt = (
        select(SessionSummary)
        .where(SessionSummary.project_id == project_id)
        .order_by(SessionSummary.created_at.desc())
        .limit(limit)
    )
    result: list[Candidate] = []
    for item in db.scalars(stmt).all():
        content = item.summary
        if item.next_action:
            content += f"\nPróxima ação: {item.next_action}"
        result.append(
            Candidate(
                kind="summary",
                title="Resumo de sessão",
                content=content,
                source_type="summary",
                source_ref=item.source_ref or f"session_summary:{item.id}",
                timestamp=item.created_at,
                importance=1.0,
            )
        )
    return result


def _decision_candidates(db: Session, project_id: UUID) -> list[Candidate]:
    stmt = (
        select(Decision)
        .where(Decision.project_id == project_id, Decision.status == "active")
        .order_by(Decision.decided_at.desc())
        .limit(100)
    )
    result: list[Candidate] = []
    for item in db.scalars(stmt).all():
        content = item.body
        if item.rationale:
            content += f"\nJustificativa: {item.rationale}"
        result.append(
            Candidate(
                kind="decision",
                title=item.title,
                content=content,
                source_type="decision",
                source_ref=item.source_ref or f"decision:{item.id}",
                timestamp=item.decided_at,
                importance=0.95,
            )
        )
    return result


def _task_candidates(db: Session, project_id: UUID) -> list[Candidate]:
    stmt = (
        select(Task)
        .where(Task.project_id == project_id, Task.status.notin_(["done", "cancelled"]))
        .order_by(Task.priority.desc(), Task.updated_at.desc())
        .limit(100)
    )
    result: list[Candidate] = []
    for item in db.scalars(stmt).all():
        lines = [f"Status: {item.status}", f"Prioridade: {item.priority}"]
        if item.description:
            lines.append(item.description)
        if item.blocked_by:
            lines.append(f"Bloqueado por: {item.blocked_by}")
        if item.due_at:
            lines.append(f"Prazo: {item.due_at.isoformat()}")
        result.append(
            Candidate(
                kind="task",
                title=item.title,
                content="\n".join(lines),
                source_type="task",
                source_ref=item.source_ref or f"task:{item.id}",
                timestamp=item.updated_at,
                importance=min(1.0, max(0.55, 0.55 + max(item.priority, 0) / 200.0)),
            )
        )
    return result


def _event_importance(event: Event) -> float:
    if event.event_type == "github.pull_request":
        return 0.92
    if event.event_type == "github.issue":
        return 0.88
    if event.event_type == "github.workflow_run":
        conclusion = str((event.metadata_json or {}).get("conclusion") or "").lower()
        return 0.95 if conclusion in {"failure", "cancelled", "timed_out"} else 0.78
    if event.event_type == "github.commit":
        return 0.76
    return 0.70


def _event_candidates(db: Session, project_id: UUID, limit: int) -> list[Candidate]:
    stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .order_by(Event.occurred_at.desc())
        .limit(limit)
    )
    result: list[Candidate] = []
    for event in db.scalars(stmt).all():
        metadata = event.metadata_json or {}
        repo = metadata.get("repository")
        conclusion = str(metadata.get("conclusion") or "").lower() or None
        content_parts = [event.body or event.title]
        if repo:
            content_parts.append(f"Repositório: {repo}")
        if event.event_type == "github.workflow_run":
            if metadata.get("status"):
                content_parts.append(f"Status: {metadata.get('status')}")
            if metadata.get("conclusion"):
                content_parts.append(f"Conclusão: {metadata.get('conclusion')}")
        result.append(
            Candidate(
                kind="event",
                title=event.title,
                content="\n".join(content_parts),
                source_type=event.source_type,
                source_ref=event.url or f"event:{event.id}",
                timestamp=event.occurred_at,
                importance=_event_importance(event),
                event_type=event.event_type,
                event_conclusion=conclusion,
            )
        )
    return result


def _context_item_candidates(db: Session, project_id: UUID, now: datetime) -> list[Candidate]:
    stmt = (
        select(ContextItem)
        .where(
            ContextItem.project_id == project_id,
            or_(ContextItem.valid_from.is_(None), ContextItem.valid_from <= now),
            or_(ContextItem.valid_to.is_(None), ContextItem.valid_to >= now),
        )
        .order_by(ContextItem.importance.desc(), ContextItem.updated_at.desc())
        .limit(250)
    )
    return [
        Candidate(
            kind=item.kind,
            title=item.title,
            content=item.content,
            source_type=item.source_type,
            source_ref=item.source_ref or f"context_item:{item.id}",
            timestamp=item.source_timestamp or item.updated_at,
            importance=item.importance,
        )
        for item in db.scalars(stmt).all()
    ]


def _candidate_key(candidate: Candidate) -> tuple[str, str | None, str]:
    return candidate.kind, candidate.source_ref, normalize_text(candidate.content)


def _reserved_operational_candidates(candidates: list[Candidate], query: str) -> list[Candidate]:
    if not has_operational_intent(query):
        return []

    selectors = (
        lambda item: item.kind == "decision",
        lambda item: item.kind == "task",
        lambda item: (
            item.kind not in {"summary", "decision", "task", "event"}
            and item.importance >= 0.90
        ),
    )

    reserved: list[Candidate] = []
    used: set[tuple[str, str | None, str]] = set()
    for selector in selectors:
        candidate = next(
            (
                item
                for item in candidates
                if selector(item) and _candidate_key(item) not in used
            ),
            None,
        )
        if candidate is None:
            continue
        reserved.append(candidate)
        used.add(_candidate_key(candidate))
    return reserved


def _is_successful_workflow_run(candidate: Candidate) -> bool:
    return candidate.event_type == "github.workflow_run" and candidate.event_conclusion == "success"


def build_context_package(
    db: Session,
    project: Project,
    query: str,
    profile: str = "standard",
    *,
    audit: bool = True,
) -> dict:
    started = perf_counter()
    if profile not in PROFILE_CONFIG:
        raise ValueError(f"Unknown context profile: {profile}")

    config = PROFILE_CONFIG[profile]
    now = datetime.now(timezone.utc)
    raw_candidates = [
        *_summary_candidates(db, project.id, config["summary_limit"]),
        *_decision_candidates(db, project.id),
        *_task_candidates(db, project.id),
        *_event_candidates(db, project.id, config["event_limit"]),
        *_context_item_candidates(db, project.id, now),
    ]
    scored = [score_candidate(candidate, query, now) for candidate in raw_candidates]
    unique = deduplicate(scored)
    unique.sort(
        key=lambda item: (item.score, item.importance, timestamp_rank(item.timestamp)),
        reverse=True,
    )

    project_description = compact_project_text(project.description)
    project_next_action = compact_project_text(project.next_action)
    project_text = "\n".join(
        filter(
            None,
            [
                project.name,
                project_description,
                f"Status: {project.status}",
                f"Próxima ação: {project_next_action}" if project_next_action else None,
            ],
        )
    )
    base_tokens = estimate_tokens(project_text) + 120
    max_tokens = int(config["max_tokens"])
    remaining = max(0, max_tokens - base_tokens)

    selected: list[Candidate] = []
    selected_keys: set[tuple[str, str | None, str]] = set()
    successful_workflow_runs = 0
    max_successful_workflow_runs = int(config["max_successful_workflow_runs"])
    reserve_item_limit = max(256, max_tokens // 5)

    for candidate in _reserved_operational_candidates(unique, query):
        if len(selected) >= int(config["max_items"]):
            break
        item = candidate
        item_limit = min(remaining, reserve_item_limit)
        if item.estimated_tokens > item_limit:
            item = compact_candidate(item, item_limit)
            if item is None:
                continue
        if item.estimated_tokens <= remaining:
            selected.append(item)
            selected_keys.add(_candidate_key(candidate))
            remaining -= item.estimated_tokens

    for candidate in unique:
        if len(selected) >= int(config["max_items"]):
            break
        if _candidate_key(candidate) in selected_keys:
            continue
        if _is_successful_workflow_run(candidate):
            if successful_workflow_runs >= max_successful_workflow_runs:
                continue
        item = candidate
        if item.estimated_tokens > remaining:
            item = compact_candidate(item, remaining)
            if item is None:
                continue
        if item.estimated_tokens <= remaining:
            selected.append(item)
            selected_keys.add(_candidate_key(candidate))
            remaining -= item.estimated_tokens
            if _is_successful_workflow_run(candidate):
                successful_workflow_runs += 1

    candidate_tokens = base_tokens + sum(item.estimated_tokens for item in unique)
    selected_tokens = base_tokens + sum(item.estimated_tokens for item in selected)
    sources: list[dict[str, str | None]] = []
    seen_sources: set[tuple[str, str | None]] = set()
    for item in selected:
        key = (item.source_type, item.source_ref)
        if key in seen_sources:
            continue
        seen_sources.add(key)
        sources.append({"source_type": item.source_type, "source_ref": item.source_ref})

    duration_ms = int((perf_counter() - started) * 1000)
    if audit:
        audit_run = ContextRun(
            project_id=project.id,
            profile=profile,
            query_text=query,
            candidate_count=len(unique),
            selected_count=len(selected),
            estimated_candidate_tokens=candidate_tokens,
            estimated_selected_tokens=selected_tokens,
            duration_ms=duration_ms,
        )
        db.add(audit_run)
        db.commit()

    return {
        "project": {
            "id": project.id,
            "slug": project.slug,
            "name": project.name,
            "description": project_description,
            "status": project.status,
            "priority": project.priority,
            "next_action": project_next_action,
            "last_activity_at": project.last_activity_at,
        },
        "query": query,
        "profile": profile,
        "items": [
            {
                "kind": item.kind,
                "title": item.title,
                "content": item.content,
                "source_type": item.source_type,
                "source_ref": item.source_ref,
                "score": item.score,
                "estimated_tokens": item.estimated_tokens,
            }
            for item in selected
        ],
        "sources": sources,
        "budget": {
            "max_tokens": max_tokens,
            "estimated_tokens": selected_tokens,
            "candidate_tokens": candidate_tokens,
            "candidate_count": len(unique),
            "selected_count": len(selected),
            "remaining_tokens": max(0, max_tokens - selected_tokens),
        },
        "generated_at": now,
    }
