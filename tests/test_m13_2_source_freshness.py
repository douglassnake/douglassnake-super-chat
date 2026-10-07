from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.dashboard import project_overview
from app.database import Base
from app.github_sync import record_github_sync_failure, sync_project_github
from app.models import Project, ProjectSource
from app.source_health import source_freshness


class EmptyGitHubReader:
    def repository(self, repository: str) -> dict:
        return {"full_name": repository, "default_branch": "main", "private": True}

    def commits(self, repository: str) -> list[dict]:
        return []

    def pulls(self, repository: str) -> list[dict]:
        return []

    def issues(self, repository: str) -> list[dict]:
        return []

    def workflow_runs(self, repository: str) -> list[dict]:
        return []


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


def test_freshness_distinguishes_never_fresh_stale_and_failed() -> None:
    now = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)
    source = ProjectSource(
        project_id=None,
        source_type="github",
        external_id="example/repo",
        label="repo",
        is_active=True,
        metadata_json={},
    )
    assert source_freshness(source, now=now, stale_after_seconds=7200)["status"] == "never"

    source.metadata_json = {"last_synced_at": (now - timedelta(minutes=30)).isoformat()}
    assert source_freshness(source, now=now, stale_after_seconds=7200)["status"] == "fresh"

    source.metadata_json = {"last_synced_at": (now - timedelta(hours=3)).isoformat()}
    assert source_freshness(source, now=now, stale_after_seconds=7200)["status"] == "stale"

    source.metadata_json = {
        "last_synced_at": (now - timedelta(minutes=30)).isoformat(),
        "last_sync_attempt_at": now.isoformat(),
        "last_sync_status": "failure",
        "last_sync_error": {"type": "GitHubAPIError", "status_code": 503},
    }
    freshness = source_freshness(source, now=now, stale_after_seconds=7200)
    assert freshness["status"] == "failed"
    assert freshness["last_error"] == {"type": "GitHubAPIError", "status_code": 503}


def test_success_and_failure_metadata_feed_project_overview() -> None:
    engine, SessionFactory = _session_factory()
    try:
        with SessionFactory() as db:
            project = Project(slug="alpha", name="Alpha", status="active")
            db.add(project)
            db.flush()
            db.add(
                ProjectSource(
                    project_id=project.id,
                    source_type="github",
                    external_id="example/alpha",
                    label="GitHub",
                    is_active=True,
                )
            )
            db.commit()
            project_id = project.id

        with SessionFactory() as db:
            project = db.get(Project, project_id)
            assert project is not None
            result = sync_project_github(db, project, reader=EmptyGitHubReader())
            assert result["source_count"] == 1
            source = db.scalar(select(ProjectSource).where(ProjectSource.project_id == project_id))
            assert source is not None
            assert source.metadata_json["last_sync_status"] == "success"
            assert source.metadata_json["last_sync_error"] is None
            assert source.metadata_json["last_sync_attempt_at"] == source.metadata_json["last_synced_at"]

        with SessionFactory() as db:
            record_github_sync_failure(
                db,
                project_id,
                {"type": "GitHubAPIError", "status_code": 403},
            )

        with SessionFactory() as db:
            overview = project_overview(db, project_id)
            assert overview is not None
            freshness = overview["sources"][0]["freshness"]
            assert freshness["status"] == "failed"
            assert freshness["last_error"] == {
                "type": "GitHubAPIError",
                "status_code": 403,
            }
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
