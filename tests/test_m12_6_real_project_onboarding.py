from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.knowledge_models import KnowledgeEntity, ProjectRelation
from app.models import ContextItem, Decision, Project, ProjectSource, Task
from scripts.onboard_projects import OnboardingManifest, apply_manifest


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def _manifest(next_action: str = "Revisar PR de planejamento") -> OnboardingManifest:
    return OnboardingManifest.model_validate(
        {
            "version": 1,
            "projects": [
                {
                    "slug": "meunegocio-ia",
                    "name": "MeuNegócio IA",
                    "description": "SaaS para pequenos negócios.",
                    "status": "active",
                    "priority": 90,
                    "next_action": next_action,
                    "sources": [
                        {
                            "source_type": "github",
                            "external_id": "douglassnake/meunegocioia",
                            "url": "https://github.com/douglassnake/meunegocioia",
                            "label": "Código principal",
                        }
                    ],
                    "decisions": [
                        {
                            "key": "m3-1-scope",
                            "title": "M3.1 autorizado com limites",
                            "body": "Implementar somente clientes e serviços.",
                            "rationale": "Preservar separação entre marcos.",
                        }
                    ],
                    "tasks": [
                        {
                            "key": "m3-1",
                            "title": "Implementar M3.1 — Clientes e serviços",
                            "priority": 90,
                        }
                    ],
                    "context_items": [
                        {
                            "key": "status-2026-10-06",
                            "kind": "status",
                            "title": "Estado atual",
                            "content": "M2 concluído e M3 planejado.",
                            "importance": 0.95,
                            "source_type": "github",
                        }
                    ],
                    "relations": [
                        {
                            "entity_name": "GitHub",
                            "entity_kind": "platform",
                            "entity_key": "github",
                            "relation_type": "uses",
                            "rationale": "Repositório principal do projeto.",
                        }
                    ],
                }
            ],
        }
    )


def test_manifest_onboarding_is_idempotent_and_updates_stable_records() -> None:
    engine, SessionFactory = _session_factory()
    try:
        with SessionFactory() as db:
            first = apply_manifest(db, _manifest())
            db.commit()

            assert first["totals"]["projects_created"] == 1
            assert first["totals"]["sources_created"] == 1
            assert first["totals"]["decisions_created"] == 1
            assert first["totals"]["tasks_created"] == 1
            assert first["totals"]["context_items_created"] == 1
            assert first["totals"]["entities_created"] == 1
            assert first["totals"]["relations_created"] == 1

        with SessionFactory() as db:
            second = apply_manifest(db, _manifest("Iniciar M3.1"))
            db.commit()

            assert second["totals"]["projects_created"] == 0
            assert second["totals"]["projects_updated"] == 1
            assert second["totals"]["sources_created"] == 0
            assert second["totals"]["decisions_created"] == 0
            assert second["totals"]["tasks_created"] == 0
            assert second["totals"]["context_items_created"] == 0
            assert second["totals"]["relations_created"] == 0

            project = db.scalar(select(Project).where(Project.slug == "meunegocio-ia"))
            assert project is not None
            assert project.next_action == "Iniciar M3.1"

            assert db.scalar(select(func.count(Project.id))) == 1
            assert db.scalar(select(func.count(ProjectSource.id))) == 1
            assert db.scalar(select(func.count(Decision.id))) == 1
            assert db.scalar(select(func.count(Task.id))) == 1
            assert db.scalar(select(func.count(ContextItem.id))) == 1
            assert db.scalar(select(func.count(KnowledgeEntity.id))) == 1
            assert db.scalar(select(func.count(ProjectRelation.id))) == 1

            decision = db.scalar(select(Decision))
            task = db.scalar(select(Task))
            memory = db.scalar(select(ContextItem))
            assert decision is not None and decision.source_ref == "m12.6:meunegocio-ia:decision:m3-1-scope"
            assert task is not None and task.source_ref == "m12.6:meunegocio-ia:task:m3-1"
            assert memory is not None and memory.source_ref == "m12.6:meunegocio-ia:context:status-2026-10-06"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_manifest_schema_rejects_unversioned_secret_fields() -> None:
    payload = {
        "version": 1,
        "projects": [
            {
                "slug": "private",
                "name": "Private",
                "github_token": "must-not-be-accepted",
            }
        ],
    }

    try:
        OnboardingManifest.model_validate(payload)
    except Exception as exc:
        assert "github_token" in str(exc)
    else:
        raise AssertionError("extra secret-like field should have been rejected")


def test_dry_run_can_be_rolled_back_without_persisting_rows() -> None:
    engine, SessionFactory = _session_factory()
    try:
        with SessionFactory() as db:
            report = apply_manifest(db, _manifest())
            assert report["totals"]["projects_created"] == 1
            db.rollback()

        with SessionFactory() as db:
            assert db.scalar(select(func.count(Project.id))) == 0
            assert db.scalar(select(func.count(ProjectSource.id))) == 0
            assert db.scalar(select(func.count(Task.id))) == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
