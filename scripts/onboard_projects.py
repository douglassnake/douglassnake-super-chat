#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.knowledge_models import KnowledgeEntity, ProjectRelation
from app.models import ContextItem, Decision, Project, ProjectSource, Task, utcnow


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSpec(StrictModel):
    source_type: str = Field(min_length=1, max_length=40)
    external_id: str | None = Field(default=None, max_length=255)
    url: str | None = None
    label: str = Field(min_length=1, max_length=255)
    metadata_json: dict = Field(default_factory=dict)
    is_active: bool = True


class DecisionSpec(StrictModel):
    key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    rationale: str | None = None
    status: str = "active"
    source_ref: str | None = None


class TaskSpec(StrictModel):
    key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: str = "todo"
    priority: int = 0
    blocked_by: str | None = None
    source_ref: str | None = None


class ContextItemSpec(StrictModel):
    key: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=1)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    source_type: str = Field(default="manual", min_length=1, max_length=50)
    source_ref: str | None = None
    generated: bool = False


SemanticRelationType = Literal[
    "uses",
    "runs_on",
    "depends_on",
    "part_of",
    "created_from",
    "supports",
    "blocks",
    "implements",
    "decided_by",
    "related_to",
    "has_document",
    "mentions",
    "describes",
]


class RelationSpec(StrictModel):
    entity_name: str = Field(min_length=1, max_length=255)
    entity_kind: str = Field(default="system", min_length=1, max_length=60)
    entity_key: str | None = Field(default=None, max_length=255)
    entity_description: str | None = None
    entity_metadata_json: dict = Field(default_factory=dict)
    relation_type: SemanticRelationType
    rationale: str | None = None
    source_ref: str | None = None


class ProjectSpec(StrictModel):
    slug: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: str = "active"
    priority: int = 0
    next_action: str | None = None
    sources: list[SourceSpec] = Field(default_factory=list)
    decisions: list[DecisionSpec] = Field(default_factory=list)
    tasks: list[TaskSpec] = Field(default_factory=list)
    context_items: list[ContextItemSpec] = Field(default_factory=list)
    relations: list[RelationSpec] = Field(default_factory=list)


class OnboardingManifest(StrictModel):
    version: Literal[1] = 1
    projects: list[ProjectSpec] = Field(min_length=1)


def _canonical_entity_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return key[:255] or "entity"


def _stable_ref(project_slug: str, section: str, key: str) -> str:
    return f"m12.6:{project_slug}:{section}:{key}"


def _set_fields(obj, values: dict) -> bool:
    changed = False
    for field, value in values.items():
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed = True
    return changed


def _validate_source(source: SourceSpec) -> None:
    if source.source_type == "github":
        repository = (source.external_id or "").strip().strip("/")
        if not repository or "/" not in repository:
            raise ValueError("GitHub source external_id must be owner/repository")


def _upsert_project(db: Session, spec: ProjectSpec, counters: dict[str, int]) -> Project:
    project = db.scalar(select(Project).where(Project.slug == spec.slug))
    values = {
        "name": spec.name,
        "description": spec.description,
        "status": spec.status,
        "priority": spec.priority,
        "next_action": spec.next_action,
    }
    if project is None:
        project = Project(slug=spec.slug, **values)
        db.add(project)
        db.flush()
        counters["projects_created"] += 1
    else:
        if _set_fields(project, values):
            project.updated_at = utcnow()
            counters["projects_updated"] += 1
        else:
            counters["projects_unchanged"] += 1
    return project


def _upsert_source(
    db: Session,
    project: Project,
    spec: SourceSpec,
    counters: dict[str, int],
) -> bool:
    _validate_source(spec)
    existing = db.scalar(
        select(ProjectSource).where(
            ProjectSource.project_id == project.id,
            ProjectSource.source_type == spec.source_type,
            ProjectSource.external_id == spec.external_id,
        )
    )
    values = {
        "url": spec.url,
        "label": spec.label,
        "metadata_json": spec.metadata_json,
        "is_active": spec.is_active,
    }
    if existing is None:
        db.add(
            ProjectSource(
                project_id=project.id,
                source_type=spec.source_type,
                external_id=spec.external_id,
                **values,
            )
        )
        counters["sources_created"] += 1
        return True
    merged_metadata = dict(existing.metadata_json or {})
    merged_metadata.update(spec.metadata_json)
    values["metadata_json"] = merged_metadata
    if _set_fields(existing, values):
        existing.updated_at = utcnow()
        counters["sources_updated"] += 1
        return True
    counters["sources_unchanged"] += 1
    return False


def _upsert_decision(
    db: Session,
    project: Project,
    project_slug: str,
    spec: DecisionSpec,
    counters: dict[str, int],
) -> bool:
    source_ref = spec.source_ref or _stable_ref(project_slug, "decision", spec.key)
    existing = db.scalar(
        select(Decision).where(
            Decision.project_id == project.id,
            Decision.source_ref == source_ref,
        )
    )
    values = {
        "title": spec.title,
        "body": spec.body,
        "rationale": spec.rationale,
        "status": spec.status,
        "source_ref": source_ref,
    }
    if existing is None:
        db.add(Decision(project_id=project.id, **values))
        counters["decisions_created"] += 1
        return True
    if _set_fields(existing, values):
        counters["decisions_updated"] += 1
        return True
    counters["decisions_unchanged"] += 1
    return False


def _upsert_task(
    db: Session,
    project: Project,
    project_slug: str,
    spec: TaskSpec,
    counters: dict[str, int],
) -> bool:
    source_ref = spec.source_ref or _stable_ref(project_slug, "task", spec.key)
    existing = db.scalar(
        select(Task).where(
            Task.project_id == project.id,
            Task.source_ref == source_ref,
        )
    )
    values = {
        "title": spec.title,
        "description": spec.description,
        "status": spec.status,
        "priority": spec.priority,
        "blocked_by": spec.blocked_by,
        "source_ref": source_ref,
    }
    if existing is None:
        db.add(Task(project_id=project.id, **values))
        counters["tasks_created"] += 1
        return True
    if _set_fields(existing, values):
        existing.updated_at = utcnow()
        counters["tasks_updated"] += 1
        return True
    counters["tasks_unchanged"] += 1
    return False


def _upsert_context_item(
    db: Session,
    project: Project,
    project_slug: str,
    spec: ContextItemSpec,
    counters: dict[str, int],
) -> bool:
    source_ref = spec.source_ref or _stable_ref(project_slug, "context", spec.key)
    existing = db.scalar(
        select(ContextItem).where(
            ContextItem.project_id == project.id,
            ContextItem.source_ref == source_ref,
        )
    )
    values = {
        "kind": spec.kind,
        "title": spec.title,
        "content": spec.content,
        "importance": spec.importance,
        "source_type": spec.source_type,
        "source_ref": source_ref,
        "generated": spec.generated,
    }
    if existing is None:
        db.add(ContextItem(project_id=project.id, **values))
        counters["context_items_created"] += 1
        return True
    if _set_fields(existing, values):
        existing.updated_at = utcnow()
        counters["context_items_updated"] += 1
        return True
    counters["context_items_unchanged"] += 1
    return False


def _upsert_relation(
    db: Session,
    project: Project,
    spec: RelationSpec,
    counters: dict[str, int],
) -> bool:
    kind = spec.entity_kind.strip().lower()
    name = spec.entity_name.strip()
    canonical_key = _canonical_entity_key(spec.entity_key or name)
    entity = db.scalar(
        select(KnowledgeEntity).where(
            KnowledgeEntity.kind == kind,
            KnowledgeEntity.canonical_key == canonical_key,
        )
    )
    changed = False
    if entity is None:
        entity = KnowledgeEntity(
            kind=kind,
            canonical_key=canonical_key,
            name=name,
            description=spec.entity_description,
            metadata_json=spec.entity_metadata_json,
            is_active=True,
        )
        db.add(entity)
        db.flush()
        counters["entities_created"] += 1
        changed = True
    else:
        merged_metadata = dict(entity.metadata_json or {})
        merged_metadata.update(spec.entity_metadata_json)
        entity_values = {
            "name": name,
            "description": spec.entity_description or entity.description,
            "metadata_json": merged_metadata,
            "is_active": True,
        }
        if _set_fields(entity, entity_values):
            entity.updated_at = utcnow()
            counters["entities_updated"] += 1
            changed = True
        else:
            counters["entities_unchanged"] += 1

    existing = db.scalar(
        select(ProjectRelation).where(
            ProjectRelation.project_id == project.id,
            ProjectRelation.entity_id == entity.id,
            ProjectRelation.relation_type == spec.relation_type,
        )
    )
    relation_values = {"is_active": True}
    if spec.rationale is not None:
        relation_values["rationale"] = spec.rationale
    if spec.source_ref is not None:
        relation_values["source_ref"] = spec.source_ref
    if existing is None:
        db.add(
            ProjectRelation(
                project_id=project.id,
                entity_id=entity.id,
                relation_type=spec.relation_type,
                **relation_values,
            )
        )
        counters["relations_created"] += 1
        return True
    if _set_fields(existing, relation_values):
        existing.updated_at = utcnow()
        counters["relations_updated"] += 1
        return True
    counters["relations_unchanged"] += 1
    return changed


def apply_manifest(db: Session, manifest: OnboardingManifest) -> dict:
    counter_names = [
        "projects_created",
        "projects_updated",
        "projects_unchanged",
        "sources_created",
        "sources_updated",
        "sources_unchanged",
        "decisions_created",
        "decisions_updated",
        "decisions_unchanged",
        "tasks_created",
        "tasks_updated",
        "tasks_unchanged",
        "context_items_created",
        "context_items_updated",
        "context_items_unchanged",
        "entities_created",
        "entities_updated",
        "entities_unchanged",
        "relations_created",
        "relations_updated",
        "relations_unchanged",
    ]
    counters = {name: 0 for name in counter_names}
    project_reports: list[dict[str, object]] = []

    for spec in manifest.projects:
        before = dict(counters)
        project = _upsert_project(db, spec, counters)
        project_changed = counters["projects_created"] > before["projects_created"] or counters[
            "projects_updated"
        ] > before["projects_updated"]

        nested_changed = False
        for source in spec.sources:
            nested_changed |= _upsert_source(db, project, source, counters)
        for decision in spec.decisions:
            nested_changed |= _upsert_decision(db, project, spec.slug, decision, counters)
        for task in spec.tasks:
            nested_changed |= _upsert_task(db, project, spec.slug, task, counters)
        for item in spec.context_items:
            nested_changed |= _upsert_context_item(db, project, spec.slug, item, counters)
        for relation in spec.relations:
            nested_changed |= _upsert_relation(db, project, relation, counters)

        if nested_changed:
            project.last_activity_at = utcnow()
            project.updated_at = utcnow()

        db.flush()
        delta = {key: counters[key] - before[key] for key in counters}
        project_reports.append(
            {
                "slug": spec.slug,
                "project_id": str(project.id),
                "changed": bool(project_changed or nested_changed),
                "counts": {key: value for key, value in delta.items() if value},
            }
        )

    return {
        "version": manifest.version,
        "projects": project_reports,
        "totals": counters,
    }


def _load_manifest(path: str) -> OnboardingManifest:
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    return OnboardingManifest.model_validate_json(raw)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently onboard real projects from a private JSON manifest. "
            "Dry-run is the default."
        )
    )
    parser.add_argument("--manifest", required=True, help="private JSON manifest path or '-' for stdin")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit changes; without this flag all database changes are rolled back",
    )
    args = parser.parse_args()

    manifest = _load_manifest(args.manifest)
    with SessionLocal() as db:
        try:
            report = apply_manifest(db, manifest)
            if args.apply:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            raise

    report["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
