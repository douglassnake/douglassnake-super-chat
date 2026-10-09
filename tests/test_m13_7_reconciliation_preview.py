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



def test_preview_does_not_expose_mutation_route():
    paths = [
        route.path
        for route in ops_routes.router.routes
        if "task-reconciliation" in route.path
    ]
    assert paths == ["/ops/task-reconciliation"]
    methods = [
        route.methods
        for route in ops_routes.router.routes
        if route.path == "/ops/task-reconciliation"
    ]
    assert methods == [{"GET"}]


def test_interface_invalidates_pending_requests():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(
        encoding="utf-8"
    )
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="reconciliation-results"' in html
    assert "++state.reconciliationRequestId" in js
    assert "state.reconciliationRequestId !== requestId" in js
    assert 'state.reconciliationRequestId += 1;' in js
    assert 'const failureUrl = safeUrl(entry.failure_run_url)' in js
    assert 'const successUrl = safeUrl(entry.success_run_url)' in js


def test_reconciliation_requires_verifiable_evidence_urls():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "task_reconciliation.py"
    ).read_text(encoding="utf-8")
    assert "if not failure.url or not last.url:" in source
    assert '"changes_applied": 0' in source


def test_ci_reconciliation_scenarios_with_isolated_fake_session(monkeypatch):
    """Exercise the real evaluator against controlled event sequences."""
    from types import SimpleNamespace
    from app import task_reconciliation as module

    project = SimpleNamespace(id=uuid4(), slug="radar-guarda-mor")
    failure = _event(title="Action V5 validation: failure")
    failure.url = "https://github.com/example/actions/runs/1"
    failure.metadata_json["conclusion"] = "failure"
    failure.metadata_json["status"] = "completed"
    task = SimpleNamespace(
        id=uuid4(),
        project_id=project.id,
        title="Investigar novas falhas de CI",
        status="todo",
        source_ref=f"event:{failure.id}",
    )

    class Results:
        def __init__(self, records):
            self.records = records
        def all(self):
            return self.records

    class Session:
        def __init__(self, runs):
            self.runs = runs
            self.calls = 0
        def scalars(self, _statement):
            self.calls += 1
            return Results(([project], [task], self.runs)[(self.calls - 1) % 3])

    def run(*, title="Action V5 validation: success", minutes=1, conclusion="success", url="https://github.com/example/actions/runs/2"):
        from datetime import timedelta
        result = _event(title=title)
        result.occurred_at = failure.occurred_at + timedelta(minutes=minutes)
        result.url = url
        result.metadata_json.update({"status": "completed", "conclusion": conclusion})
        return result

    cases = [
        ([failure, run()], 1),
        ([failure, run(title="Action unrelated workflow: success")], 0),
        ([failure, run(minutes=-1)], 0),
        ([failure, run(conclusion="failure")], 0),
        ([failure, run(url=None)], 0),
        ([failure, run(), run(minutes=2, conclusion="failure")], 0),
    ]
    for events, expected in cases:
        report = module.collect_ci_reconciliation_hints(Session(events), project_slug=project.slug)
        assert report["suggestion_count"] == expected
        assert report["changes_applied"] == 0
