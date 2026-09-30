from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.github_onboarding import _current_failed_workflows
from app.models import Event, Project


def _event(project_id, *, run_id: int, conclusion: str, branch: str, when: str) -> Event:
    dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
    return Event(
        project_id=project_id,
        source_type="github",
        event_type="github.workflow_run",
        external_id=f"repo:run:{run_id}",
        title=f"Action tests: {conclusion}",
        occurred_at=dt,
        url=f"https://github.com/example/repo/actions/runs/{run_id}",
        metadata_json={
            "repository": "example/repo",
            "run_id": run_id,
            "status": "completed",
            "conclusion": conclusion,
            "head_branch": branch,
        },
    )


def test_historical_failure_does_not_survive_newer_success() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        project = Project(id=uuid4(), slug="quality", name="Quality")
        db.add(project)
        db.flush()
        db.add_all(
            [
                _event(
                    project.id,
                    run_id=1,
                    conclusion="failure",
                    branch="main",
                    when="2026-09-29T10:00:00Z",
                ),
                _event(
                    project.id,
                    run_id=2,
                    conclusion="success",
                    branch="main",
                    when="2026-09-29T11:00:00Z",
                ),
            ]
        )
        db.commit()

        failed = _current_failed_workflows(
            db,
            project.id,
            default_branch_by_repository={"example/repo": "main"},
        )
        assert failed == []


def test_feature_branch_failure_does_not_override_green_default_branch() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        project = Project(id=uuid4(), slug="branches", name="Branches")
        db.add(project)
        db.flush()
        db.add_all(
            [
                _event(
                    project.id,
                    run_id=10,
                    conclusion="success",
                    branch="main",
                    when="2026-09-29T11:00:00Z",
                ),
                _event(
                    project.id,
                    run_id=11,
                    conclusion="failure",
                    branch="feature/test",
                    when="2026-09-29T12:00:00Z",
                ),
            ]
        )
        db.commit()

        failed = _current_failed_workflows(
            db,
            project.id,
            default_branch_by_repository={"example/repo": "main"},
        )
        assert failed == []
