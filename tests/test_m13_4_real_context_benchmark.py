from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import ContextItem, ContextRun, Decision, Project, Task
import scripts.real_context_benchmark as real_benchmark


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return engine, SessionFactory


def test_real_benchmark_is_read_only_and_can_defer_semantic_search(monkeypatch) -> None:
    engine, SessionFactory = _session_factory()
    try:
        with SessionFactory() as db:
            project = Project(
                slug="real-a",
                name="Real A",
                status="active",
                next_action="Validar backup",
            )
            db.add(project)
            db.flush()
            db.add(
                Task(
                    project_id=project.id,
                    title="Automatizar backup e restore",
                    description="Rotina periódica de backup e restore.",
                    status="todo",
                    priority=90,
                )
            )
            db.add(
                Decision(
                    project_id=project.id,
                    title="Usar Caddy compartilhado",
                    body="HTTPS interno usa o Caddy compartilhado.",
                    status="active",
                    decided_at=datetime.now(timezone.utc),
                )
            )
            db.add(
                ContextItem(
                    project_id=project.id,
                    kind="deployment",
                    title="Implantação no NAS",
                    content="PostgreSQL persistente no NAS.",
                    importance=1.0,
                    source_type="manual",
                )
            )
            db.commit()

        monkeypatch.setattr(real_benchmark, "SessionLocal", SessionFactory)

        manifest = {
            "name": "real-test",
            "thresholds": {
                "min_mean_recall": 0.9,
                "critical_requires_full_recall": True,
            },
            "cases": [
                {
                    "name": "ops",
                    "project_slug": "real-a",
                    "query": "backup restore Caddy implantação NAS decisão tarefa",
                    "profile": "standard",
                    "k": 5,
                    "critical": True,
                    "expected": [
                        {"kind": "task", "title_contains": "backup"},
                        {"kind": "decision", "title_contains": "Caddy"},
                        {"kind": "deployment", "title_contains": "NAS"},
                    ],
                }
            ],
        }

        report = real_benchmark.run_real_benchmark(manifest)
        assert report["summary"]["gate_passed"] is True
        assert report["summary"]["m7_1_decision"] == "defer_m7_1"
        assert report["results"][0]["recall_at_k"] == 1.0

        with SessionFactory() as db:
            assert db.scalar(select(func.count(ContextRun.id))) == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_real_benchmark_requires_semantic_prototype_when_critical_recall_misses(monkeypatch) -> None:
    engine, SessionFactory = _session_factory()
    try:
        with SessionFactory() as db:
            project = Project(slug="real-b", name="Real B", status="active")
            db.add(project)
            db.flush()
            db.add(
                ContextItem(
                    project_id=project.id,
                    kind="note",
                    title="Unrelated",
                    content="Conteúdo sem relação com a expectativa.",
                    importance=0.5,
                    source_type="manual",
                )
            )
            db.commit()

        monkeypatch.setattr(real_benchmark, "SessionLocal", SessionFactory)

        report = real_benchmark.run_real_benchmark(
            {
                "cases": [
                    {
                        "name": "critical miss",
                        "project_slug": "real-b",
                        "query": "arquitetura decisao critica",
                        "profile": "minimal",
                        "k": 3,
                        "critical": True,
                        "expected": [
                            {"kind": "decision", "title_contains": "inexistente"}
                        ],
                    }
                ]
            }
        )

        assert report["summary"]["gate_passed"] is False
        assert report["summary"]["m7_1_decision"] == "prototype_semantic_and_compare"
        assert report["summary"]["critical_failures"] == ["critical miss"]
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
