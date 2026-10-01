from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge_models import KnowledgeEntity, KnowledgeRelation, ProjectRelation
from app.models import ContextItem, Decision, Project, ProjectSource, SessionDelta, Task


SEMANTIC_RELATION_LABELS = {
    "uses": "USES",
    "runs_on": "RUNS_ON",
    "depends_on": "DEPENDS_ON",
    "part_of": "PART_OF",
    "created_from": "CREATED_FROM",
    "supports": "SUPPORTS",
    "blocks": "BLOCKS",
    "implements": "IMPLEMENTS",
    "decided_by": "DECIDED_BY",
    "related_to": "RELATED_TO",
    "has_document": "HAS_DOCUMENT",
    "mentions": "MENTIONS",
    "describes": "DESCRIBES",
}


def _node_id(kind: str, entity_id: UUID | str) -> str:
    return f"{kind}:{entity_id}"


def _source_identity(source: ProjectSource) -> str:
    raw = (source.external_id or source.url or str(source.id)).strip().lower()
    digest = sha1(f"{source.source_type}|{raw}".encode("utf-8")).hexdigest()[:20]
    return f"source:{digest}"


def _project_node(project: Project) -> dict[str, Any]:
    return {
        "id": _node_id("project", project.id),
        "entity_id": str(project.id),
        "type": "project",
        "label": project.name,
        "subtitle": project.status,
        "project_id": str(project.id),
        "importance": max(0.35, min(1.0, (project.priority + 20) / 120)),
        "metadata": {
            "slug": project.slug,
            "status": project.status,
            "priority": project.priority,
            "next_action": project.next_action,
            "description": project.description,
        },
    }


def build_knowledge_graph(db: Session) -> dict[str, Any]:
    """Build the read-only graph from persisted operational and semantic records."""

    projects = list(
        db.scalars(
            select(Project).order_by(Project.priority.desc(), Project.name.asc())
        ).all()
    )
    project_ids = {project.id for project in projects}

    tasks = list(
        db.scalars(
            select(Task)
            .where(
                Task.project_id.is_not(None),
                Task.status.notin_(["done", "cancelled"]),
            )
            .order_by(Task.priority.desc(), Task.created_at.desc())
        ).all()
    )
    decisions = list(
        db.scalars(
            select(Decision)
            .where(Decision.project_id.is_not(None), Decision.status == "active")
            .order_by(Decision.decided_at.desc())
        ).all()
    )
    memories = list(
        db.scalars(
            select(ContextItem)
            .where(ContextItem.project_id.is_not(None), ContextItem.valid_to.is_(None))
            .order_by(ContextItem.importance.desc(), ContextItem.updated_at.desc())
        ).all()
    )
    sources = list(
        db.scalars(
            select(ProjectSource)
            .where(ProjectSource.is_active.is_(True))
            .order_by(ProjectSource.source_type.asc(), ProjectSource.label.asc())
        ).all()
    )
    deltas = list(
        db.scalars(
            select(SessionDelta)
            .where(SessionDelta.status == "pending")
            .order_by(SessionDelta.created_at.desc())
        ).all()
    )
    project_relations = list(
        db.scalars(
            select(ProjectRelation)
            .where(ProjectRelation.is_active.is_(True))
            .order_by(ProjectRelation.relation_type.asc(), ProjectRelation.created_at.asc())
        ).all()
    )
    knowledge_relations = list(
        db.scalars(
            select(KnowledgeRelation)
            .where(KnowledgeRelation.is_active.is_(True))
            .order_by(KnowledgeRelation.relation_type.asc(), KnowledgeRelation.created_at.asc())
        ).all()
    )

    nodes: list[dict[str, Any]] = [_project_node(project) for project in projects]
    edges: list[dict[str, Any]] = []

    for task in tasks:
        if task.project_id not in project_ids:
            continue
        node_id = _node_id("task", task.id)
        nodes.append(
            {
                "id": node_id,
                "entity_id": str(task.id),
                "type": "task",
                "label": task.title,
                "subtitle": task.status,
                "project_id": str(task.project_id),
                "importance": max(0.25, min(1.0, task.priority / 100)),
                "metadata": {
                    "status": task.status,
                    "priority": task.priority,
                    "description": task.description,
                    "due_at": task.due_at,
                    "blocked_by": task.blocked_by,
                    "source_ref": task.source_ref,
                },
            }
        )
        edges.append(
            {
                "id": f"edge:project-task:{task.id}",
                "source": _node_id("project", task.project_id),
                "target": node_id,
                "type": "has_task",
                "label": "tarefa",
            }
        )

    for decision in decisions:
        if decision.project_id not in project_ids:
            continue
        node_id = _node_id("decision", decision.id)
        nodes.append(
            {
                "id": node_id,
                "entity_id": str(decision.id),
                "type": "decision",
                "label": decision.title,
                "subtitle": decision.status,
                "project_id": str(decision.project_id),
                "importance": 0.72,
                "metadata": {
                    "status": decision.status,
                    "body": decision.body,
                    "rationale": decision.rationale,
                    "decided_at": decision.decided_at,
                    "source_ref": decision.source_ref,
                },
            }
        )
        edges.append(
            {
                "id": f"edge:project-decision:{decision.id}",
                "source": _node_id("project", decision.project_id),
                "target": node_id,
                "type": "has_decision",
                "label": "decisão",
            }
        )

    for memory in memories:
        if memory.project_id not in project_ids:
            continue
        node_id = _node_id("memory", memory.id)
        nodes.append(
            {
                "id": node_id,
                "entity_id": str(memory.id),
                "type": "memory",
                "label": memory.title or memory.kind,
                "subtitle": memory.kind,
                "project_id": str(memory.project_id),
                "importance": max(0.25, min(1.0, memory.importance)),
                "metadata": {
                    "kind": memory.kind,
                    "content": memory.content,
                    "importance": memory.importance,
                    "source_type": memory.source_type,
                    "source_ref": memory.source_ref,
                    "generated": memory.generated,
                },
            }
        )
        edges.append(
            {
                "id": f"edge:project-memory:{memory.id}",
                "source": _node_id("project", memory.project_id),
                "target": node_id,
                "type": "has_memory",
                "label": "memória",
            }
        )

    source_nodes: dict[str, dict[str, Any]] = {}
    for source in sources:
        if source.project_id not in project_ids:
            continue
        node_id = _source_identity(source)
        if node_id not in source_nodes:
            source_nodes[node_id] = {
                "id": node_id,
                "entity_id": str(source.id),
                "type": "source",
                "label": source.label,
                "subtitle": source.source_type,
                "project_id": str(source.project_id),
                "project_ids": [str(source.project_id)],
                "importance": 0.82,
                "metadata": {
                    "source_type": source.source_type,
                    "external_id": source.external_id,
                    "url": source.url,
                    "labels": [source.label],
                },
            }
        else:
            node = source_nodes[node_id]
            project_id = str(source.project_id)
            if project_id not in node["project_ids"]:
                node["project_ids"].append(project_id)
            if source.label not in node["metadata"]["labels"]:
                node["metadata"]["labels"].append(source.label)

        edges.append(
            {
                "id": f"edge:project-source:{source.id}",
                "source": _node_id("project", source.project_id),
                "target": node_id,
                "type": "uses_source",
                "label": "fonte",
            }
        )
    nodes.extend(source_nodes.values())

    for delta in deltas:
        if delta.project_id not in project_ids:
            continue
        node_id = _node_id("delta", delta.id)
        nodes.append(
            {
                "id": node_id,
                "entity_id": str(delta.id),
                "type": "delta",
                "label": delta.session_key,
                "subtitle": "aguardando revisão",
                "project_id": str(delta.project_id),
                "importance": 0.65,
                "metadata": {
                    "summary": delta.summary,
                    "next_action": delta.next_action,
                    "created_at": delta.created_at,
                },
            }
        )
        edges.append(
            {
                "id": f"edge:project-delta:{delta.id}",
                "source": _node_id("project", delta.project_id),
                "target": node_id,
                "type": "has_pending_delta",
                "label": "revisão",
            }
        )

    # Semantic entities are canonical records. M11.5 propagates project scope through
    # entity-to-entity relations so document/entity connections remain visible when a
    # target is known only through the document that mentions it.
    entity_project_ids: dict[UUID, set[UUID]] = defaultdict(set)
    for relation in project_relations:
        if relation.project_id in project_ids:
            entity_project_ids[relation.entity_id].add(relation.project_id)

    changed = True
    while changed:
        changed = False
        for relation in knowledge_relations:
            source_projects = entity_project_ids.get(relation.source_entity_id, set())
            target_projects = entity_project_ids.get(relation.target_entity_id, set())
            combined = source_projects | target_projects
            if not combined:
                continue
            for entity_id in (relation.source_entity_id, relation.target_entity_id):
                before = len(entity_project_ids[entity_id])
                entity_project_ids[entity_id].update(combined)
                if len(entity_project_ids[entity_id]) != before:
                    changed = True

    semantic_nodes: dict[UUID, dict[str, Any]] = {}
    for entity_id, scoped_projects in entity_project_ids.items():
        entity = db.get(KnowledgeEntity, entity_id)
        if entity is None or not entity.is_active:
            continue
        entity_metadata = dict(entity.metadata_json or {})
        node_type = "document" if entity.kind == "document" else "entity"
        project_id_values = sorted(str(value) for value in scoped_projects)
        semantic_nodes[entity.id] = {
            "id": _node_id(node_type, entity.id),
            "entity_id": str(entity.id),
            "type": node_type,
            "label": entity.name,
            "subtitle": (
                entity_metadata.get("document_type")
                or entity_metadata.get("source_type")
                or entity.kind
            ),
            "project_id": project_id_values[0] if project_id_values else None,
            "project_ids": project_id_values,
            "importance": 0.82 if node_type == "document" else 0.78,
            "metadata": {
                "kind": entity.kind,
                "canonical_key": entity.canonical_key,
                "description": entity.description,
                "document_type": entity_metadata.get("document_type"),
                "source_type": entity_metadata.get("source_type"),
                "external_id": entity_metadata.get("external_id"),
                "url": entity_metadata.get("url"),
                "metadata": entity_metadata,
            },
        }
    nodes.extend(semantic_nodes.values())

    for relation in project_relations:
        if relation.project_id not in project_ids:
            continue
        entity = db.get(KnowledgeEntity, relation.entity_id)
        node = semantic_nodes.get(relation.entity_id)
        if entity is None or node is None:
            continue
        edges.append(
            {
                "id": f"edge:semantic:{relation.id}",
                "source": _node_id("project", relation.project_id),
                "target": node["id"],
                "type": relation.relation_type,
                "label": SEMANTIC_RELATION_LABELS.get(
                    relation.relation_type,
                    relation.relation_type.upper(),
                ),
                "semantic": True,
                "metadata": {
                    "relation_id": str(relation.id),
                    "relation_scope": "project",
                    "rationale": relation.rationale,
                    "source_ref": relation.source_ref,
                },
            }
        )

    for relation in knowledge_relations:
        source = semantic_nodes.get(relation.source_entity_id)
        target = semantic_nodes.get(relation.target_entity_id)
        if source is None or target is None:
            continue
        edges.append(
            {
                "id": f"edge:knowledge:{relation.id}",
                "source": source["id"],
                "target": target["id"],
                "type": relation.relation_type,
                "label": SEMANTIC_RELATION_LABELS.get(
                    relation.relation_type,
                    relation.relation_type.upper(),
                ),
                "semantic": True,
                "metadata": {
                    "relation_id": str(relation.id),
                    "relation_scope": "knowledge",
                    "rationale": relation.rationale,
                    "source_ref": relation.source_ref,
                },
            }
        )

    counts = Counter(node["type"] for node in nodes)
    return {
        "generated_at": datetime.now(timezone.utc),
        "nodes": nodes,
        "edges": edges,
        "counts": dict(counts),
        "relation_types": sorted({edge["type"] for edge in edges}),
    }
