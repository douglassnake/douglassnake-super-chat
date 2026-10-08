from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Event, Project, Task
from app.task_reconciliation import collect_ci_reconciliation_hints


def _database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )


def _seed(SessionFactory, *, branch="main", repository="sample/repo"):
    start = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    with SessionFactory() as db:
        project = Project(slug="example", name="Example", status="active")
        db.add(project)
        db.flush()
        failure = _event(
            project.id, start, "failure", branch=branch, repository=repository
        )
        db.add(failure)
        db.flush()
        task = Task(
            project_id=project.id,
            title="Investigar novas falhas de CI",
            status="todo",
            source_ref=f"event:{failure.id}",
        )
        db.add(task)
        db.commit()
        return project.id, task.id, failure.id, start


def _event(
    project_id, date, conclusion, *, branch="main", repository="sample/repo",
    name="Validate", status="completed",
):
    return Event(
        project_id=project_id,
        source_type="github",
        event_type="github.workflow_run",
        title=f"Action {name}: {conclusion}",
        occurred_at=date,
        url=f"https://github.com/{repository}/actions/runs/{int(date.timestamp())}",
        metadata_json={
            "repository": repository,
            "head_branch": branch,
            "conclusion": conclusion,
            "status": status,
        },
    )


def test_later_success_suggests_review_without_writing_anything():
    engine, factory = _database()
    try:
        pid, task_id, _, start = _seed(factory)
        with factory() as db:
            db.add(_event(pid, start + timedelta(minutes=2), "success"))
            db.commit()
            before = db.scalar(select(func.count(Task.id)))
            result = collect_ci_reconciliation_hints(db)
            assert result["mode"] == "check"
            assert result["changes_applied"] == 0
            assert result["ci_tasks_examined"] == 1
            assert result["suggestion_count"] == 1
            suggestion = result["suggestions"][0]
            assert suggestion["task_id"] == str(task_id)
            assert suggestion["recommendation"] == "review_possible_ci_resolution"
            assert suggestion["failure_run_url"]
            assert suggestion["success_run_url"]
            assert db.get(Task, task_id).status == "todo"
            assert db.scalar(select(func.count(Task.id))) == before
            assert not db.new and not db.dirty and not db.deleted
    finally:
        engine.dispose()


def test_newer_failure_blocks_resolution_hint():
    engine, factory = _database()
    try:
        pid, _, _, start = _seed(factory)
        with factory() as db:
            db.add_all([
                _event(pid, start + timedelta(minutes=1), "success"),
                _event(pid, start + timedelta(minutes=2), "failure"),
            ])
            db.commit()
            assert collect_ci_reconciliation_hints(db)["suggestion_count"] == 0
    finally:
        engine.dispose()


def test_success_on_another_branch_or_repo_does_not_count():
    engine, factory = _database()
    try:
        pid, _, _, start = _seed(factory)
        with factory() as db:
            db.add_all([
                _event(pid, start + timedelta(minutes=1), "success", branch="feature"),
                _event(pid, start + timedelta(minutes=2), "success", repository="other/repo"),
                _event(pid, start + timedelta(minutes=3), "success", name="Deploy"),
            ])
            db.commit()
            assert collect_ci_reconciliation_hints(db)["suggestion_count"] == 0
    finally:
        engine.dispose()


def test_unfinished_run_does_not_count_as_resolution():
    engine, factory = _database()
    try:
        pid, _, _, start = _seed(factory)
        with factory() as db:
            db.add(_event(pid, start + timedelta(minutes=1), "success", status="in_progress"))
            db.commit()
            assert collect_ci_reconciliation_hints(db)["suggestion_count"] == 0
    finally:
        engine.dispose()


def test_closed_and_unattributed_tasks_are_never_suggested():
    engine, factory = _database()
    try:
        pid, tid, _, start = _seed(factory)
        with factory() as db:
            db.add(_event(pid, start + timedelta(minutes=1), "success"))
            db.commit()
            db.get(Task, tid).status = "done"
            db.add(
                Task(project_id=pid, title="Investigar novas falhas de CI",
                     status="todo", source_ref="manual:ci")
            )
            db.commit()
            result = collect_ci_reconciliation_hints(db)
            assert result["open_tasks_examined"] == 1
            assert result["suggestion_count"] == 0
    finally:
        engine.dispose()


def test_project_filter_does_not_leak_suggestions_between_projects():
    engine, factory = _database()
    try:
        pid, _, _, start = _seed(factory)
        with factory() as db:
            db.add(_event(pid, start + timedelta(minutes=1), "success"))
            db.add(Project(slug="other", name="Other", status="active"))
            db.commit()
            result = collect_ci_reconciliation_hints(db, project_slug="other")
            assert result["project_count"] == 1
            assert result["suggestion_count"] == 0
    finally:
        engine.dispose()
