from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph_suggestion_schemas import GraphRelationSuggestion
from app.knowledge_models import (
    GraphSuggestionBatch,
    KnowledgeEntity,
    KnowledgeRelation,
    ProjectRelation,
)
from app.models import ContextItem, Decision, Project, ProjectSource, Task, utcnow


SOURCE_ENTITY_MAP: dict[str, tuple[str, str, str, str]] = {
    "github": ("GitHub", "platform", "github", "Plataforma de código-fonte e colaboração usada pelo projeto."),
    "google_drive": ("Google Drive", "platform", "google-drive", "Armazenamento de documentos conectado ao projeto."),
    "google_calendar": ("Google Calendar", "service", "google-calendar", "Agenda conectada ao projeto."),
}


@dataclass(frozen=True)
class EvidenceRecord:
    text: str
    source_ref: str


def canonical_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return key[:255] or "entity"


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()


def normalized_source_type(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalized_text(value or "")).strip("_")


def _snippet(text: str, needle: str, radius: int = 115) -> str:
    plain = normalized_text(text)
    target = normalized_text(needle)
    index = plain.find(target)
    if index < 0:
        return text[:240].strip()
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = f"…{snippet}"
    if end < len(text):
        snippet = f"{snippet}…"
    return snippet


def _relation_from_context(entity: KnowledgeEntity, text: str) -> str:
    value = normalized_text(text)
    if any(token in value for token in ("roda em", "rodando em", "executa em", "executando em", "implantado no", "implantada no", "hospedado", "hospedada", "hosted on")):
        return "runs_on"
    if any(token in value for token in ("depende de", "dependencia", "dependency", "depends on")):
        return "depends_on"
    if entity.kind == "database" and any(token in value for token in ("banco", "database", "persist", "armazena")):
        return "depends_on"
    if any(token in value for token in (" usa ", " utiliza ", " via ", "proxy", "integracao", "integrado", "fonte", "conectado")):
        return "uses"
    return "related_to"


def _project_evidence(db: Session, project: Project) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []

    project_text = "\n".join(
        part for part in (project.name, project.description, project.next_action) if part
    )
    if project_text:
        records.append(EvidenceRecord(project_text, f"project:{project.id}"))

    memories = db.scalars(
        select(ContextItem).where(
            ContextItem.project_id == project.id,
            ContextItem.valid_to.is_(None),
        )
    ).all()
    for item in memories:
        text = "\n".join(part for part in (item.title, item.content) if part)
        if text:
            records.append(EvidenceRecord(text, f"context_item:{item.id}"))

    decisions = db.scalars(
        select(Decision).where(Decision.project_id == project.id, Decision.status == "active")
    ).all()
    for item in decisions:
        text = "\n".join(part for part in (item.title, item.body, item.rationale) if part)
        if text:
            records.append(EvidenceRecord(text, f"decision:{item.id}"))

    tasks = db.scalars(
        select(Task).where(
            Task.project_id == project.id,
            Task.status.notin_(["done", "cancelled"]),
        )
    ).all()
    for item in tasks:
        text = "\n".join(part for part in (item.title, item.description) if part)
        if text:
            records.append(EvidenceRecord(text, f"task:{item.id}"))

    document_relations = db.scalars(
        select(ProjectRelation).where(
            ProjectRelation.project_id == project.id,
            ProjectRelation.is_active.is_(True),
            ProjectRelation.relation_type == "has_document",
        )
    ).all()
    for relation in document_relations:
        entity = db.get(KnowledgeEntity, relation.entity_id)
        if entity is None or not entity.is_active or entity.kind != "document":
            continue
        metadata = dict(entity.metadata_json or {})
        text = "\n".join(
            str(part)
            for part in (
                entity.name,
                entity.description,
                relation.rationale,
                metadata.get("source_type"),
                metadata.get("external_id"),
                metadata.get("url"),
            )
            if part
        )
        if text:
            records.append(EvidenceRecord(text, f"document:{entity.id}"))

    return records


def _project_documents(db: Session, project: Project) -> list[tuple[KnowledgeEntity, ProjectRelation]]:
    result: list[tuple[KnowledgeEntity, ProjectRelation]] = []
    relations = db.scalars(
        select(ProjectRelation).where(
            ProjectRelation.project_id == project.id,
            ProjectRelation.is_active.is_(True),
            ProjectRelation.relation_type == "has_document",
        )
    ).all()
    for relation in relations:
        entity = db.get(KnowledgeEntity, relation.entity_id)
        if entity is not None and entity.is_active and entity.kind == "document":
            result.append((entity, relation))
    return result


def discover_relation_suggestions(db: Session, project: Project) -> list[GraphRelationSuggestion]:
    active_relations = list(
        db.scalars(
            select(ProjectRelation).where(
                ProjectRelation.project_id == project.id,
                ProjectRelation.is_active.is_(True),
            )
        ).all()
    )
    already_related_entity_ids = {relation.entity_id for relation in active_relations}
    active_knowledge_relations = list(
        db.scalars(select(KnowledgeRelation).where(KnowledgeRelation.is_active.is_(True))).all()
    )
    suggestions: list[GraphRelationSuggestion] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add_suggestion(suggestion: GraphRelationSuggestion) -> None:
        subject_key = (
            str(suggestion.subject_entity_id)
            if suggestion.subject_type == "entity"
            else str(project.id)
        )
        key = (
            suggestion.subject_type,
            subject_key,
            suggestion.entity_kind,
            suggestion.entity_key,
            suggestion.relation_type,
        )
        if key in seen:
            return
        existing_entity = db.scalar(
            select(KnowledgeEntity).where(
                KnowledgeEntity.kind == suggestion.entity_kind,
                KnowledgeEntity.canonical_key == suggestion.entity_key,
                KnowledgeEntity.is_active.is_(True),
            )
        )
        if suggestion.subject_type == "project":
            if existing_entity is not None and existing_entity.id in already_related_entity_ids:
                return
        elif suggestion.subject_entity_id is not None and existing_entity is not None:
            if any(
                relation.source_entity_id == suggestion.subject_entity_id
                and relation.target_entity_id == existing_entity.id
                and relation.relation_type == suggestion.relation_type
                for relation in active_knowledge_relations
            ):
                return
        seen.add(key)
        suggestions.append(suggestion)

    sources = list(
        db.scalars(
            select(ProjectSource).where(
                ProjectSource.project_id == project.id,
                ProjectSource.is_active.is_(True),
            )
        ).all()
    )
    for source in sources:
        mapped = SOURCE_ENTITY_MAP.get(source.source_type)
        if mapped is None:
            continue
        name, kind, key, description = mapped
        evidence_value = source.external_id or source.url or source.label
        add_suggestion(
            GraphRelationSuggestion(
                entity_name=name,
                entity_kind=kind,
                entity_key=key,
                entity_description=description,
                relation_type="uses",
                rationale=f"O projeto possui uma fonte {source.source_type} ativa vinculada.",
                evidence=f"Fonte ativa: {source.label} · {evidence_value}",
                source_ref=f"project_source:{source.id}",
                confidence=0.98,
            )
        )

    evidence_records = _project_evidence(db, project)
    entities = list(
        db.scalars(
            select(KnowledgeEntity).where(
                KnowledgeEntity.is_active.is_(True),
                KnowledgeEntity.kind != "document",
            )
        ).all()
    )
    for entity in entities:
        if entity.id in already_related_entity_ids:
            continue
        name_key = normalized_text(entity.name).strip()
        if len(name_key) < 3:
            continue
        for record in evidence_records:
            if name_key not in normalized_text(record.text):
                continue
            relation_type = _relation_from_context(entity, record.text)
            add_suggestion(
                GraphRelationSuggestion(
                    entity_name=entity.name,
                    entity_kind=entity.kind,
                    entity_key=entity.canonical_key,
                    entity_description=entity.description,
                    relation_type=relation_type,
                    rationale=f"{entity.name} é mencionado no contexto persistente do projeto.",
                    evidence=_snippet(record.text, entity.name),
                    source_ref=record.source_ref,
                    confidence=0.84 if relation_type != "related_to" else 0.74,
                )
            )
            break

    # M11.5: documents become active subjects in discovery instead of passive project attachments.
    # Source metadata creates high-confidence CREATED_FROM links, while explicit mentions in
    # persisted document metadata/description create MENTIONS links to known entities.
    for document, project_relation in _project_documents(db, project):
        metadata = dict(document.metadata_json or {})
        document_text = "\n".join(
            str(part)
            for part in (
                document.name,
                document.description,
                project_relation.rationale,
                metadata.get("source_type"),
                metadata.get("external_id"),
                metadata.get("url"),
            )
            if part
        )
        explicit_target: tuple[str, str] | None = None
        source_type = normalized_source_type(metadata.get("source_type"))
        mapped = SOURCE_ENTITY_MAP.get(source_type)
        if mapped is not None:
            name, kind, key, description = mapped
            explicit_target = (kind, key)
            add_suggestion(
                GraphRelationSuggestion(
                    subject_type="entity",
                    subject_entity_id=document.id,
                    subject_label=document.name,
                    entity_name=name,
                    entity_kind=kind,
                    entity_key=key,
                    entity_description=description,
                    relation_type="created_from",
                    rationale=f"{document.name} está registrado como documento originado em {name}.",
                    evidence=_snippet(document_text, metadata.get("source_type") or name),
                    source_ref=f"document:{document.id}",
                    confidence=0.97,
                )
            )

        normalized_document = normalized_text(document_text)
        for entity in entities:
            if explicit_target == (entity.kind, entity.canonical_key):
                continue
            entity_name = normalized_text(entity.name).strip()
            if len(entity_name) < 3 or entity_name not in normalized_document:
                continue
            add_suggestion(
                GraphRelationSuggestion(
                    subject_type="entity",
                    subject_entity_id=document.id,
                    subject_label=document.name,
                    entity_name=entity.name,
                    entity_kind=entity.kind,
                    entity_key=entity.canonical_key,
                    entity_description=entity.description,
                    relation_type="mentions",
                    rationale=f"{document.name} menciona {entity.name} em seu contexto persistido.",
                    evidence=_snippet(document_text, entity.name),
                    source_ref=f"document:{document.id}",
                    confidence=0.88,
                )
            )

    suggestions.sort(
        key=lambda item: (
            -item.confidence,
            item.subject_label or project.name,
            item.entity_name.lower(),
            item.relation_type,
        )
    )
    return suggestions[:16]


def create_suggestion_batch(db: Session, project: Project) -> GraphSuggestionBatch:
    existing = db.scalar(
        select(GraphSuggestionBatch)
        .where(
            GraphSuggestionBatch.project_id == project.id,
            GraphSuggestionBatch.status == "pending",
        )
        .order_by(GraphSuggestionBatch.created_at.desc())
    )
    if existing is not None and existing.suggestions_json:
        return existing
    if existing is not None:
        existing.status = "superseded"
        existing.discarded_at = utcnow()
        db.flush()

    suggestions = discover_relation_suggestions(db, project)
    source_refs = sorted({item.source_ref for item in suggestions if item.source_ref})
    if suggestions:
        summary = (
            f"Foram encontradas {len(suggestions)} conexão(ões) candidata(s) para {project.name}. "
            "Nada será persistido até revisão humana e aplicação explícita."
        )
    else:
        summary = (
            f"Nenhuma conexão nova foi encontrada para {project.name} com as evidências disponíveis. "
            "Relações existentes e duplicatas foram ignoradas."
        )
    batch = GraphSuggestionBatch(
        project_id=project.id,
        status="pending",
        summary=summary,
        suggestions_json=[item.model_dump(mode="json") for item in suggestions],
        source_refs_json=source_refs,
    )
    db.add(batch)
    project.last_activity_at = utcnow()
    project.updated_at = utcnow()
    db.commit()
    db.refresh(batch)
    return batch


def _target_entity(db: Session, suggestion: GraphRelationSuggestion) -> KnowledgeEntity:
    entity = db.scalar(
        select(KnowledgeEntity).where(
            KnowledgeEntity.kind == suggestion.entity_kind,
            KnowledgeEntity.canonical_key == suggestion.entity_key,
        )
    )
    if entity is None:
        entity = KnowledgeEntity(
            kind=suggestion.entity_kind,
            canonical_key=suggestion.entity_key,
            name=suggestion.entity_name,
            description=suggestion.entity_description,
            metadata_json={"discovered_by": "graph-suggestions"},
            is_active=True,
        )
        db.add(entity)
        db.flush()
    else:
        entity.is_active = True
        if suggestion.entity_description and not entity.description:
            entity.description = suggestion.entity_description
        entity.updated_at = utcnow()
    return entity


def apply_suggestion_batch(
    db: Session,
    batch: GraphSuggestionBatch,
    selected_indexes: list[int],
) -> tuple[int, int]:
    if batch.status != "pending":
        raise ValueError("Suggestion batch is not pending")

    suggestions = [GraphRelationSuggestion.model_validate(item) for item in batch.suggestions_json]
    selected = sorted(set(selected_indexes))
    if any(index < 0 or index >= len(suggestions) for index in selected):
        raise IndexError("Suggestion index out of range")

    applied = 0
    skipped = 0
    for index in selected:
        suggestion = suggestions[index]
        entity = _target_entity(db, suggestion)

        if suggestion.subject_type == "entity":
            if suggestion.subject_entity_id is None:
                skipped += 1
                continue
            subject = db.get(KnowledgeEntity, suggestion.subject_entity_id)
            if subject is None or not subject.is_active or subject.id == entity.id:
                skipped += 1
                continue
            project_link = db.scalar(
                select(ProjectRelation).where(
                    ProjectRelation.project_id == batch.project_id,
                    ProjectRelation.entity_id == subject.id,
                    ProjectRelation.is_active.is_(True),
                )
            )
            if project_link is None:
                skipped += 1
                continue
            relation = db.scalar(
                select(KnowledgeRelation).where(
                    KnowledgeRelation.source_entity_id == subject.id,
                    KnowledgeRelation.target_entity_id == entity.id,
                    KnowledgeRelation.relation_type == suggestion.relation_type,
                )
            )
            if relation is not None and relation.is_active:
                skipped += 1
                continue
            if relation is None:
                relation = KnowledgeRelation(
                    source_entity_id=subject.id,
                    target_entity_id=entity.id,
                    relation_type=suggestion.relation_type,
                    rationale=suggestion.rationale,
                    source_ref=suggestion.source_ref,
                    is_active=True,
                )
                db.add(relation)
            else:
                relation.is_active = True
                relation.rationale = suggestion.rationale
                relation.source_ref = suggestion.source_ref
                relation.updated_at = utcnow()
            applied += 1
            continue

        relation = db.scalar(
            select(ProjectRelation).where(
                ProjectRelation.project_id == batch.project_id,
                ProjectRelation.entity_id == entity.id,
                ProjectRelation.relation_type == suggestion.relation_type,
            )
        )
        if relation is not None and relation.is_active:
            skipped += 1
            continue
        if relation is None:
            relation = ProjectRelation(
                project_id=batch.project_id,
                entity_id=entity.id,
                relation_type=suggestion.relation_type,
                rationale=suggestion.rationale,
                source_ref=suggestion.source_ref,
                is_active=True,
            )
            db.add(relation)
        else:
            relation.is_active = True
            relation.rationale = suggestion.rationale
            relation.source_ref = suggestion.source_ref
            relation.updated_at = utcnow()
        applied += 1

    batch.status = "applied"
    batch.applied_at = utcnow()
    project = db.get(Project, batch.project_id)
    if project is not None:
        project.last_activity_at = utcnow()
        project.updated_at = utcnow()
    db.commit()
    return applied, skipped


def discard_suggestion_batch(db: Session, batch: GraphSuggestionBatch) -> None:
    if batch.status != "pending":
        raise ValueError("Suggestion batch is not pending")
    batch.status = "discarded"
    batch.discarded_at = utcnow()
    db.commit()
