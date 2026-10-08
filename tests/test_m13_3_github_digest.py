from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.github_digest import prepare_automatic_github_digest, prepare_github_digest
from app.models import Event, Project, ProjectSource, SessionDelta, SessionSummary, Task
from app.session_memory import apply_session_delta, discard_session_delta


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


def _seed_project(SessionFactory):
    with SessionFactory() as db:
        project = Project(slug="digest-project", name="Digest Project", status="active")
        db.add(project)
        db.flush()
        db.add(
            ProjectSource(
                project_id=project.id,
                source_type="github",
                external_id="example/digest-project",
                label="GitHub",
                is_active=True,
                metadata_json={},
            )
        )
        db.commit()
        return project.id


def _add_event(SessionFactory, project_id, *, event_type, title, created_at, metadata=None):
    with SessionFactory() as db:
        event = Event(
            project_id=project_id,
            source_type="github",
            event_type=event_type,
            external_id=f"{event_type}:{title}:{created_at.isoformat()}",
            title=title,
            body=None,
            occurred_at=created_at,
            created_at=created_at,
            metadata_json=metadata or {},
        )
        db.add(event)
        db.commit()
        return event.id


def test_digest_requires_review_before_tasks_or_summary_are_created() -> None:
    engine, SessionFactory = _session_factory()
    try:
        project_id = _seed_project(SessionFactory)
        now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        _add_event(
            SessionFactory,
            project_id,
            event_type="github.issue",
            title="Issue #10: revisar integração",
            created_at=now,
            metadata={"state": "open"},
        )
        _add_event(
            SessionFactory,
            project_id,
            event_type="github.pull_request",
            title="PR #11: implementar integração",
            created_at=now + timedelta(seconds=1),
            metadata={"state": "open"},
        )

        with SessionFactory() as db:
            project = db.get(Project, project_id)
            result = prepare_github_digest(db, project)
            assert result["created"] is True
            delta = result["delta"]
            assert delta.status == "pending"
            assert len(delta.tasks_json) == 2

        with SessionFactory() as db:
            assert db.scalar(select(func.count(Task.id))) == 0
            assert db.scalar(select(func.count(SessionSummary.id))) == 0
            delta = db.scalar(select(SessionDelta).where(SessionDelta.project_id == project_id))
            assert delta is not None
            applied = apply_session_delta(db, delta)
            assert len(applied["created_task_ids"]) == 2

        with SessionFactory() as db:
            assert db.scalar(select(func.count(Task.id))) == 2
            assert db.scalar(select(func.count(SessionSummary.id))) == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_discarded_digest_events_are_not_suggested_again() -> None:
    engine, SessionFactory = _session_factory()
    try:
        project_id = _seed_project(SessionFactory)
        now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        _add_event(
            SessionFactory,
            project_id,
            event_type="github.commit",
            title="Commit abc1234: docs",
            created_at=now,
        )

        with SessionFactory() as db:
            project = db.get(Project, project_id)
            first = prepare_github_digest(db, project)
            assert first["created"] is True
            discard_session_delta(db, first["delta"])

        with SessionFactory() as db:
            project = db.get(Project, project_id)
            second = prepare_github_digest(db, project)
            assert second["created"] is False
            assert second["event_count"] == 0
            assert db.scalar(select(func.count(SessionDelta.id))) == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_automatic_digest_baselines_history_then_queues_only_new_events() -> None:
    engine, SessionFactory = _session_factory()
    try:
        project_id = _seed_project(SessionFactory)
        sync_start = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        _add_event(
            SessionFactory,
            project_id,
            event_type="github.commit",
            title="Commit old0001: historical",
            created_at=sync_start - timedelta(hours=2),
        )

        with SessionFactory() as db:
            project = db.get(Project, project_id)
            baseline = prepare_automatic_github_digest(
                db,
                project,
                sync_started_at=sync_start,
                sync_completed_at=sync_start + timedelta(seconds=10),
            )
            assert baseline["created"] is False
            assert baseline["event_count"] == 0

        new_event_at = sync_start + timedelta(minutes=5)
        _add_event(
            SessionFactory,
            project_id,
            event_type="github.workflow_run",
            title="Action tests: failure",
            created_at=new_event_at,
            metadata={"conclusion": "failure"},
        )

        with SessionFactory() as db:
            project = db.get(Project, project_id)
            queued = prepare_automatic_github_digest(
                db,
                project,
                sync_started_at=new_event_at - timedelta(seconds=10),
                sync_completed_at=new_event_at + timedelta(seconds=10),
            )
            assert queued["created"] is True
            assert queued["event_count"] == 1
            assert queued["suggested_tasks"] == 1
            delta = queued["delta"]
            assert delta.status == "pending"
            assert delta.tasks_json[0]["title"] == "Investigar novas falhas de CI"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_existing_pending_digest_blocks_parallel_digest_batch() -> None:
    engine, SessionFactory = _session_factory()
    try:
        project_id = _seed_project(SessionFactory)
        now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        _add_event(
            SessionFactory,
            project_id,
            event_type="github.issue",
            title="Issue #20: primeira",
            created_at=now,
        )

        with SessionFactory() as db:
            project = db.get(Project, project_id)
            first = prepare_github_digest(db, project)
            assert first["created"] is True

        _add_event(
            SessionFactory,
            project_id,
            event_type="github.issue",
            title="Issue #21: segunda",
            created_at=now + timedelta(minutes=1),
        )

        with SessionFactory() as db:
            project = db.get(Project, project_id)
            second = prepare_github_digest(db, project)
            assert second["created"] is False
            assert second["pending_exists"] is True
            assert db.scalar(select(func.count(SessionDelta.id))) == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
