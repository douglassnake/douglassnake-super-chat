"""M13.8: authorize, audit, and replay manual reviews without changing tasks."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.reconciliation_review_routes import ReviewRequest, record_review


class FakeSession:
    def __init__(self, task):
        self.task = task
        self.events = []
        self.commits = 0

    def scalar(self, query):
        from app.models import Task
        entity = query.column_descriptions[0]["entity"]
        if entity is Task:
            return self.task
        return self.events[0] if self.events else None

    def add(self, value):
        self.events.append(value)

    def commit(self):
        self.commits += 1


def _context(*, authorized=True, enabled=True):
    request = SimpleNamespace(
        state=SimpleNamespace(
            authenticated=authorized,
            auth_principal={"username": "operator", "role": "admin"} if authorized else None,
        ),
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(auth_enabled=enabled))),
    )
    task = SimpleNamespace(
        id=uuid4(), project_id=uuid4(), status="todo",
        updated_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )
    payload = ReviewRequest(
        task_id=task.id, request_id=uuid4(),
        expected_updated_at=task.updated_at.isoformat(),
        decision="needs_investigation",
        justification="Revisão manual com evidências verificadas no GitHub.",
        evidence_urls=["https://github.com/example/repo/actions/runs/10"],
    )
    return request, task, payload


def test_review_records_audit_without_closing_task():
    request, task, payload = _context()
    db = FakeSession(task)
    result = record_review(payload, request, db)
    assert result["changes_applied"] == 0
    assert task.status == "todo"
    assert db.commits == 1
    assert db.events[0].metadata_json["actor"] == "operator"
    assert db.events[0].metadata_json["decision"] == "needs_investigation"


def test_review_rejects_unauthenticated_and_disabled_auth():
    for authorized, enabled, code in [(False, True, 401), (True, False, 403)]:
        request, task, payload = _context(authorized=authorized, enabled=enabled)
        db = FakeSession(task)
        with pytest.raises(HTTPException) as exc:
            record_review(payload, request, db)
        assert exc.value.status_code == code
        assert db.commits == 0


def test_review_replay_is_idempotent():
    request, task, payload = _context()
    db = FakeSession(task)
    first = record_review(payload, request, db)
    second = record_review(payload, request, db)
    assert first == second
    assert db.commits == 1
    assert len(db.events) == 1


def test_review_rejects_modified_payload_on_same_key():
    request, task, payload = _context()
    db = FakeSession(task)
    record_review(payload, request, db)
    other = payload.model_copy(update={"justification": "Outra justificativa de revisão operacional."})
    with pytest.raises(HTTPException) as exc:
        record_review(other, request, db)
    assert exc.value.status_code == 409


def test_review_rejects_invalid_evidence_url_and_stale_task():
    request, task, payload = _context()
    db = FakeSession(task)
    with pytest.raises(HTTPException) as exc:
        record_review(payload.model_copy(update={"evidence_urls": ["https://evil.example/"]}), request, db)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        record_review(payload.model_copy(update={"expected_updated_at": "2025-01-01T00:00:00Z"}), request, db)
    assert exc.value.status_code == 409
    assert db.commits == 0


def test_review_rejects_non_admin_and_closed_task():
    request, task, payload = _context()
    request.state.auth_principal["role"] = "viewer"
    with pytest.raises(HTTPException) as exc:
        record_review(payload, request, FakeSession(task))
    assert exc.value.status_code == 403
    request.state.auth_principal["role"] = "admin"
    task.status = "done"
    with pytest.raises(HTTPException) as exc:
        record_review(payload, request, FakeSession(task))
    assert exc.value.status_code == 409


def test_review_interface_requires_explicit_confirmation_and_preserves_key():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'window.confirm("Registrar revisão auditável sem concluir a tarefa?")' in js
    assert "control.dataset.reviewRequestId ||" in js
    assert 'method: "POST"' in js
    assert "justification.length < 15" in js
