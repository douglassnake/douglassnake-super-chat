from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.github_sync import GitHubAPIError
from app.models import Project, ProjectSource
from scripts.ops_github_sync import (
    _safe_error,
    build_check_report,
    sync_active_github_projects,
)


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


def _seed_project(
    SessionFactory,
    *,
    slug: str,
    status: str = "active",
    github_active: bool | None = True,
) -> None:
    with SessionFactory() as db:
        project = Project(slug=slug, name=slug, status=status)
        db.add(project)
        db.flush()
        if github_active is not None:
            db.add(
                ProjectSource(
                    project_id=project.id,
                    source_type="github",
                    external_id=f"example/{slug}",
                    label="Código",
                    is_active=github_active,
                )
            )
        db.commit()


def test_check_lists_only_active_projects_with_active_github_sources() -> None:
    engine, SessionFactory = _session_factory()
    try:
        _seed_project(SessionFactory, slug="alpha")
        _seed_project(SessionFactory, slug="inactive-project", status="paused")
        _seed_project(SessionFactory, slug="inactive-source", github_active=False)
        _seed_project(SessionFactory, slug="no-source", github_active=None)

        report = build_check_report(SessionFactory)

        assert report["mode"] == "check"
        assert report["totals"] == {
            "eligible_projects": 1,
            "source_count": 1,
        }
        assert [item["slug"] for item in report["projects"]] == ["alpha"]
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_sync_continues_after_project_failure_and_aggregates_counts() -> None:
    engine, SessionFactory = _session_factory()
    try:
        _seed_project(SessionFactory, slug="alpha")
        _seed_project(SessionFactory, slug="beta")

        calls: list[str] = []

        def fake_sync(db: Session, project: Project) -> dict:
            calls.append(project.slug)
            if project.slug == "alpha":
                raise GitHubAPIError("sensitive upstream response", status_code=503)
            return {
                "source_count": 1,
                "created_events": 2,
                "skipped_events": 5,
            }

        report = sync_active_github_projects(SessionFactory, fake_sync)

        assert calls == ["alpha", "beta"]
        assert report["totals"]["eligible_projects"] == 2
        assert report["totals"]["successful_projects"] == 1
        assert report["totals"]["failed_projects"] == 1
        assert report["totals"]["created_events"] == 2
        assert report["totals"]["skipped_events"] == 5

        alpha = next(item for item in report["projects"] if item["slug"] == "alpha")
        beta = next(item for item in report["projects"] if item["slug"] == "beta")
        assert alpha["status"] == "failure"
        assert alpha["error"] == {"type": "GitHubAPIError", "status_code": 503}
        assert beta["status"] == "success"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_error_reports_never_include_exception_message_or_token_text() -> None:
    github_error = GitHubAPIError(
        "Authorization Bearer ghp_should_never_appear",
        status_code=403,
    )
    generic_error = RuntimeError("DATABASE_URL=postgresql://secret")

    rendered = json.dumps(
        {
            "github": _safe_error(github_error),
            "generic": _safe_error(generic_error),
        }
    )

    assert "ghp_should_never_appear" not in rendered
    assert "postgresql://secret" not in rendered
    assert _safe_error(github_error) == {
        "type": "GitHubAPIError",
        "status_code": 403,
    }
    assert _safe_error(generic_error) == {"type": "RuntimeError"}


def test_successful_repeat_can_report_zero_new_events() -> None:
    engine, SessionFactory = _session_factory()
    try:
        _seed_project(SessionFactory, slug="repeat")

        def fake_repeat(db: Session, project: Project) -> dict:
            return {
                "source_count": 1,
                "created_events": 0,
                "skipped_events": 20,
            }

        report = sync_active_github_projects(SessionFactory, fake_repeat)

        assert report["totals"]["failed_projects"] == 0
        assert report["totals"]["created_events"] == 0
        assert report["totals"]["skipped_events"] == 20
        assert report["projects"][0]["status"] == "success"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_host_wrapper_sets_pythonpath_for_script_imports() -> None:
    wrapper = Path("scripts/ops_github_sync.sh").read_text(encoding="utf-8")
    assert "-e PYTHONPATH=/app" in wrapper
    assert "python scripts/ops_github_sync.py" in wrapper
