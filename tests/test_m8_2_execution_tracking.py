from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def execution_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _approved_pack(client: TestClient) -> dict:
    project = client.post(
        "/projects",
        json={
            "slug": "execution-project",
            "name": "Execution Project",
            "status": "implementation",
            "next_action": "Acompanhar execução com evidências",
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    context = client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "decision",
            "title": "Gate de evidência",
            "content": "Concluir somente após evidência explícita. token=context-secret",
            "importance": 1.0,
            "source_type": "manual",
            "source_ref": "manual:execution-gate",
        },
    )
    assert context.status_code == 201

    created = client.post(
        "/agent-task-packs",
        json={
            "project_id": project_id,
            "objective": "Implementar e validar acompanhamento de execução",
            "acceptance_criteria": [
                "A suíte de testes deve passar",
                "O resultado deve preservar a trilha de auditoria",
            ],
            "constraints": ["Não fazer merge ou deploy"],
            "suggested_areas": ["app/execution_routes.py", "tests/test_m8_2_execution_tracking.py"],
            "profile": "minimal",
            "query": "execução evidência testes auditoria",
        },
    )
    assert created.status_code == 201
    approved = client.post(f"/agent-task-packs/{created.json()['id']}/approve")
    assert approved.status_code == 200
    return approved.json()


def _handoff(client: TestClient, pack_id: str, *, release: bool) -> dict:
    created = client.post(
        f"/agent-task-packs/{pack_id}/handoffs",
        json={
            "executor_type": "codex",
            "executor_target": "local-worktree",
            "allowed_actions": ["read_repository", "modify_worktree", "run_tests", "create_commit"],
        },
    )
    assert created.status_code == 201
    handoff = created.json()
    if release:
        released = client.post(f"/agent-handoffs/{handoff['id']}/release")
        assert released.status_code == 200
        handoff = released.json()
    return handoff


def _execution(client: TestClient, handoff_id: str) -> dict:
    created = client.post(f"/agent-handoffs/{handoff_id}/execution")
    assert created.status_code == 201
    return created.json()


def test_execution_requires_release_is_unique_and_starts_with_pending_criteria(
    execution_client: TestClient,
) -> None:
    client = execution_client
    pack = _approved_pack(client)
    handoff = _handoff(client, pack["id"], release=False)

    blocked = client.post(f"/agent-handoffs/{handoff['id']}/execution")
    assert blocked.status_code == 409

    released = client.post(f"/agent-handoffs/{handoff['id']}/release")
    assert released.status_code == 200

    created = client.post(f"/agent-handoffs/{handoff['id']}/execution")
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "running"
    assert body["progress_percent"] == 0
    assert body["event_sequence"] == 1
    assert body["criteria_coverage"] == {
        "total": 2,
        "passed": 0,
        "failed": 0,
        "pending": 2,
        "complete_allowed": False,
    }
    assert [item["status"] for item in body["criteria"]] == ["pending", "pending"]

    duplicate = client.post(f"/agent-handoffs/{handoff['id']}/execution")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["execution_id"] == body["id"]

    by_handoff = client.get(f"/agent-handoffs/{handoff['id']}/execution")
    assert by_handoff.status_code == 200
    assert by_handoff.json()["id"] == body["id"]

    events = client.get(f"/agent-executions/{body['id']}/events")
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert events.json()[0]["sequence"] == 1
    assert events.json()[0]["event_type"] == "started"


def test_progress_and_technical_references_are_append_only_and_redacted(
    execution_client: TestClient,
) -> None:
    client = execution_client
    pack = _approved_pack(client)
    handoff = _handoff(client, pack["id"], release=True)
    execution = _execution(client, handoff["id"])

    progress = client.post(
        f"/agent-executions/{execution['id']}/progress",
        json={
            "progress_percent": 40,
            "current_step": "Rodando testes token=step-secret",
            "message": "pytest em andamento api_key=message-secret",
        },
    )
    assert progress.status_code == 200
    progress_body = progress.json()
    assert progress_body["progress_percent"] == 40
    assert "step-secret" not in str(progress_body).lower()
    assert "[redacted]" in str(progress_body).lower()

    refs = client.post(
        f"/agent-executions/{execution['id']}/technical-refs",
        json={
            "branch_ref": "codex/m8-2-execution-tracking",
            "commit_sha": "abc123def456",
            "pr_url": "https://example.test/pr/21?token=pr-secret&view=files",
            "message": "Referências observadas password=refs-secret",
        },
    )
    assert refs.status_code == 200
    refs_body = refs.json()
    assert refs_body["branch_ref"] == "codex/m8-2-execution-tracking"
    assert refs_body["commit_sha"] == "abc123def456"
    assert "pr-secret" not in refs_body["pr_url"]
    assert "%5BREDACTED%5D" in refs_body["pr_url"] or "[REDACTED]" in refs_body["pr_url"]
    assert refs_body["event_sequence"] == 3

    empty_refs = client.post(
        f"/agent-executions/{execution['id']}/technical-refs",
        json={},
    )
    assert empty_refs.status_code == 422

    events = client.get(f"/agent-executions/{execution['id']}/events")
    assert events.status_code == 200
    event_list = events.json()
    assert [event["sequence"] for event in event_list] == [1, 2, 3]
    assert [event["event_type"] for event in event_list] == ["started", "progress", "technical_refs"]
    serialized = str(event_list).lower()
    assert "message-secret" not in serialized
    assert "refs-secret" not in serialized


def test_evidence_gate_blocks_bypass_and_requires_latest_passed_evidence(
    execution_client: TestClient,
) -> None:
    client = execution_client
    pack = _approved_pack(client)
    handoff = _handoff(client, pack["id"], release=True)
    execution = _execution(client, handoff["id"])

    direct_handoff_complete = client.post(
        f"/agent-handoffs/{handoff['id']}/complete",
        json={"result": {"summary": "bypass"}},
    )
    assert direct_handoff_complete.status_code == 409
    assert direct_handoff_complete.json()["detail"]["execution_id"] == execution["id"]

    premature = client.post(
        f"/agent-executions/{execution['id']}/complete",
        json={"summary": "Ainda sem evidências"},
    )
    assert premature.status_code == 409
    assert premature.json()["detail"]["criteria_coverage"]["pending"] == 2

    invalid_index = client.post(
        f"/agent-executions/{execution['id']}/evidence",
        json={
            "criterion_index": 9,
            "status": "passed",
            "evidence_type": "test",
            "summary": "índice inexistente",
        },
    )
    assert invalid_index.status_code == 422

    first_failed = client.post(
        f"/agent-executions/{execution['id']}/evidence",
        json={
            "criterion_index": 0,
            "status": "failed",
            "evidence_type": "pytest",
            "summary": "Um teste falhou token=evidence-secret",
            "reference": "https://example.test/actions/1?token=evidence-ref-secret",
            "payload": {"failed": 1},
        },
    )
    assert first_failed.status_code == 200
    assert first_failed.json()["criteria"][0]["status"] == "failed"
    assert "evidence-secret" not in str(first_failed.json()).lower()
    assert "evidence-ref-secret" not in str(first_failed.json()).lower()

    second_passed = client.post(
        f"/agent-executions/{execution['id']}/evidence",
        json={
            "criterion_index": 1,
            "status": "passed",
            "evidence_type": "audit",
            "summary": "Trilha de auditoria verificada",
            "reference": "event-log:1-4",
        },
    )
    assert second_passed.status_code == 200

    still_blocked = client.post(
        f"/agent-executions/{execution['id']}/complete",
        json={"summary": "Primeiro critério ainda falhou"},
    )
    assert still_blocked.status_code == 409
    assert still_blocked.json()["detail"]["criteria_coverage"]["failed"] == 1

    first_recovered = client.post(
        f"/agent-executions/{execution['id']}/evidence",
        json={
            "criterion_index": 0,
            "status": "passed",
            "evidence_type": "pytest",
            "summary": "Suíte verde na segunda execução",
            "reference": "actions:green",
            "payload": {"passed": 30, "failed": 0},
        },
    )
    assert first_recovered.status_code == 200
    recovered_body = first_recovered.json()
    assert recovered_body["criteria_coverage"]["passed"] == 2
    assert recovered_body["criteria_coverage"]["complete_allowed"] is True
    assert recovered_body["criteria"][0]["status"] == "passed"

    completed = client.post(
        f"/agent-executions/{execution['id']}/complete",
        json={
            "summary": "Critérios verificados",
            "result": {"commit": "abc123", "secret": "result-secret"},
        },
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert completed_body["status"] == "completed"
    assert completed_body["progress_percent"] == 100
    assert completed_body["criteria_coverage"]["complete_allowed"] is True
    assert "result-secret" not in str(completed_body).lower()

    handoff_after = client.get(f"/agent-handoffs/{handoff['id']}")
    assert handoff_after.status_code == 200
    assert handoff_after.json()["status"] == "completed"
    assert handoff_after.json()["completed_at"] is not None

    evidence_after_completion = client.post(
        f"/agent-executions/{execution['id']}/evidence",
        json={
            "criterion_index": 0,
            "status": "failed",
            "evidence_type": "late",
            "summary": "não pode alterar depois",
        },
    )
    assert evidence_after_completion.status_code == 409

    repeated_complete = client.post(
        f"/agent-executions/{execution['id']}/complete",
        json={"summary": "não sobrescrever", "result": {"different": True}},
    )
    assert repeated_complete.status_code == 200
    assert repeated_complete.json()["completed_at"] == completed_body["completed_at"]
    assert repeated_complete.json()["result"] == completed_body["result"]


def test_fail_and_cancel_sync_handoff_and_terminal_transitions_are_idempotent(
    execution_client: TestClient,
) -> None:
    client = execution_client
    pack = _approved_pack(client)

    failing_handoff = _handoff(client, pack["id"], release=True)
    failing_execution = _execution(client, failing_handoff["id"])

    failed = client.post(
        f"/agent-executions/{failing_execution['id']}/fail",
        json={
            "error": "Falha técnica password=failure-secret",
            "result": {"stage": "pytest", "token": "result-failure-secret"},
        },
    )
    assert failed.status_code == 200
    failed_body = failed.json()
    assert failed_body["status"] == "failed"
    assert failed_body["failed_at"] is not None
    assert "failure-secret" not in str(failed_body).lower()
    failed_at = failed_body["failed_at"]

    failed_handoff = client.get(f"/agent-handoffs/{failing_handoff['id']}")
    assert failed_handoff.json()["status"] == "failed"

    repeated_fail = client.post(
        f"/agent-executions/{failing_execution['id']}/fail",
        json={"error": "não sobrescrever", "result": {}},
    )
    assert repeated_fail.status_code == 200
    assert repeated_fail.json()["failed_at"] == failed_at
    assert repeated_fail.json()["result"] == failed_body["result"]

    cancel_handoff = _handoff(client, pack["id"], release=True)
    cancel_execution = _execution(client, cancel_handoff["id"])

    direct_cancel = client.post(f"/agent-handoffs/{cancel_handoff['id']}/cancel")
    assert direct_cancel.status_code == 409

    cancelled = client.post(f"/agent-executions/{cancel_execution['id']}/cancel")
    assert cancelled.status_code == 200
    cancelled_body = cancelled.json()
    assert cancelled_body["status"] == "cancelled"
    assert cancelled_body["cancelled_at"] is not None
    cancelled_at = cancelled_body["cancelled_at"]

    cancelled_handoff = client.get(f"/agent-handoffs/{cancel_handoff['id']}")
    assert cancelled_handoff.json()["status"] == "cancelled"

    repeated_cancel = client.post(f"/agent-executions/{cancel_execution['id']}/cancel")
    assert repeated_cancel.status_code == 200
    assert repeated_cancel.json()["cancelled_at"] == cancelled_at

    events = client.get(f"/agent-executions/{cancel_execution['id']}/events")
    assert events.status_code == 200
    assert [event["sequence"] for event in events.json()] == [1, 2]
    assert events.json()[-1]["payload"]["status"] == "cancelled"
