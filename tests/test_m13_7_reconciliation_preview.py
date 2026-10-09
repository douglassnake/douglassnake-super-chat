"""M13.7: regression tests for conservative, read-only CI reconciliation."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app import ops_routes
from app.task_reconciliation import _source_event_id, _workflow_identity


def _event(*, repo="douglassnake/radar-guardamor", branch="main", title="Action Coletar calibracao V5: failure"):
    return SimpleNamespace(
        id=uuid4(),
        source_type="github",
        event_type="github.workflow_run",
        metadata_json={"repository": repo, "head_branch": branch},
        title=title,
        occurred_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )


def test_workflow_identity_requires_repository_workflow_and_branch():
    event = _event()
    assert _workflow_identity(event) == (
        "douglassnake/radar-guardamor", "Coletar calibracao V5", "main"
    )
    assert _workflow_identity(_event(branch="")) is None
    assert _workflow_identity(_event(repo="")) is None
    assert _workflow_identity(_event(title="Unknown workflow")) is None


def test_only_event_uuid_refs_are_accepted():
    event_id = uuid4()
    assert _source_event_id(f"event:{event_id}") == event_id
    assert _source_event_id("https://github.com/example") is None
    assert _source_event_id("event:not-a-uuid") is None
    assert _source_event_id(None) is None


def test_ops_preview_delegates_without_writes(monkeypatch):
    sentinel = object()
    observed = []

    def fake_collect(db, *, project_slug=None):
        observed.append((db, project_slug))
        return {"mode": "check", "changes_applied": 0, "suggestions": []}

    monkeypatch.setattr(ops_routes, "collect_ci_reconciliation_hints", fake_collect)
    result = ops_routes.task_reconciliation_preview(project_slug="radar-guarda-mor", db=sentinel)
    assert observed == [(sentinel, "radar-guarda-mor")]
    assert result["changes_applied"] == 0
    assert result["suggestions"] == []
