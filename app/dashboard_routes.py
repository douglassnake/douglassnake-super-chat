import re
import unicodedata
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dashboard import dashboard_payload, project_overview
from app.database import get_db
from app.knowledge_graph import build_knowledge_graph
from app.knowledge_models import KnowledgeEntity, KnowledgeRelation, ProjectRelation
from app.knowledge_schemas import KnowledgeEntityRead, ProjectRelationCreate, ProjectRelationRead
from app.models import Project, utcnow

router = APIRouter(tags=["dashboard"])


def _canonical_entity_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return key[:255] or "entity"


def _relation_payload(relation: ProjectRelation, entity: KnowledgeEntity) -> ProjectRelationRead:
    return ProjectRelationRead(
        id=relation.id,
        project_id=relation.project_id,
        entity_id=relation.entity_id,
        relation_type=relation.relation_type,
        rationale=relation.rationale,
        source_ref=relation.source_ref,
        is_active=relation.is_active,
        created_at=relation.created_at,
        updated_at=relation.updated_at,
        entity=KnowledgeEntityRead.model_validate(entity),
    )


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    return dashboard_payload(db)


@router.get("/graph")
def get_knowledge_graph(db: Session = Depends(get_db)) -> dict:
    return build_knowledge_graph(db)


@router.post(
    "/projects/{project_id}/relations",
    response_model=ProjectRelationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_relation(
    project_id: UUID,
    payload: ProjectRelationCreate,
    db: Session = Depends(get_db),
) -> ProjectRelationRead:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    kind = payload.entity_kind.strip().lower()
    name = payload.entity_name.strip()
    canonical_key = _canonical_entity_key(payload.entity_key or name)
    entity = db.scalar(
        select(KnowledgeEntity).where(
            KnowledgeEntity.kind == kind,
            KnowledgeEntity.canonical_key == canonical_key,
        )
    )
    if entity is None:
        entity = KnowledgeEntity(
            kind=kind,
            canonical_key=canonical_key,
            name=name,
            description=payload.entity_description,
            metadata_json=payload.entity_metadata_json,
            is_active=True,
        )
        db.add(entity)
        db.flush()
    else:
        entity.is_active = True
        if payload.entity_description and not entity.description:
            entity.description = payload.entity_description
        if payload.entity_metadata_json:
            merged = dict(entity.metadata_json or {})
            merged.update(payload.entity_metadata_json)
            entity.metadata_json = merged
        entity.updated_at = utcnow()

    existing = db.scalar(
        select(ProjectRelation).where(
            ProjectRelation.project_id == project_id,
            ProjectRelation.entity_id == entity.id,
            ProjectRelation.relation_type == payload.relation_type,
        )
    )
    if existing is not None and existing.is_active:
        raise HTTPException(status_code=409, detail="Semantic relation already exists")

    if existing is None:
        relation = ProjectRelation(
            project_id=project_id,
            entity_id=entity.id,
            relation_type=payload.relation_type,
            rationale=payload.rationale,
            source_ref=payload.source_ref,
            is_active=True,
        )
        db.add(relation)
    else:
        relation = existing
        relation.is_active = True
        relation.rationale = payload.rationale
        relation.source_ref = payload.source_ref
        relation.updated_at = utcnow()

    project.last_activity_at = utcnow()
    project.updated_at = utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Semantic relation already exists") from exc
    db.refresh(entity)
    db.refresh(relation)
    return _relation_payload(relation, entity)


@router.get("/projects/{project_id}/relations", response_model=list[ProjectRelationRead])
def list_project_relations(project_id: UUID, db: Session = Depends(get_db)) -> list[ProjectRelationRead]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    relations = list(
        db.scalars(
            select(ProjectRelation)
            .where(ProjectRelation.project_id == project_id, ProjectRelation.is_active.is_(True))
            .order_by(ProjectRelation.relation_type.asc(), ProjectRelation.created_at.asc())
        ).all()
    )
    result: list[ProjectRelationRead] = []
    for relation in relations:
        entity = db.get(KnowledgeEntity, relation.entity_id)
        if entity is not None and entity.is_active:
            result.append(_relation_payload(relation, entity))
    return result


@router.delete("/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_relation(relation_id: UUID, db: Session = Depends(get_db)) -> Response:
    relation = db.get(ProjectRelation, relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail="Semantic relation not found")
    relation.is_active = False
    relation.updated_at = utcnow()
    project = db.get(Project, relation.project_id)
    if project is not None:
        project.last_activity_at = utcnow()
        project.updated_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/knowledge-relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_relation(relation_id: UUID, db: Session = Depends(get_db)) -> Response:
    relation = db.get(KnowledgeRelation, relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail="Knowledge relation not found")
    relation.is_active = False
    relation.updated_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/overview")
def get_project_overview(project_id: UUID, db: Session = Depends(get_db)) -> dict:
    payload = project_overview(db, project_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return payload
