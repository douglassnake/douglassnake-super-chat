from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.github_verification_routes as verification_routes
from app.database import Base, get_db
from app.github_sync import GitHubAPIError
from app.github_verification import verify_execution_github as real_verify_execution_github
from app.main import app


class FakeVerificationReader:
    def __init__(
        self,
        *,
        commit_sha: str = "abc123456789",
        pr_number: int = 7,
        pr_repository: str = "douglassnake/example",
        checks: list[dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.commit_sha = commit_sha
        self.pr_number = pr_number
        self.pr_repository = pr_repository
        self.checks = checks if checks is not None else [
            {
                "id": 100,
                "name": "pytest",
                "status": "completed",
                "conclusion": "success",
                "details_url": "https://github.com/douglassnake/example/actions/runs/100",
                "started_at": "2026-09-18T20:00:00Z",
                "completed_at": "2026-09-18T20:01:00Z",
            },
            {
                "id": 101,
                "name": "benchmark",
                "status": "completed",
                "conclusion": "success",
                "details_url": "https://github.com/douglassnake/example/actions/runs/101",
                "started_at": "2026-09-18T20:01:00Z",
                "completed_at": "2026-09-18T20:02:00Z",
            },
        ]
        self.error = error
        self.calls: list[tuple] = []

    def _raise_if_needed(self) -> None:
        if self.error is not None:
            raise self.error

    def commit(self, repository: str, sha: str) -> dict:
        self.calls.append(("commit", repository, sha))
        self._raise_if_needed()
        return {
            "sha": self.commit_sha,
            "html_url": f"https://github.com/{repository}/commit/{self.commit_sha}",
            "commit": {"message": "feat: verified change\n\nDetails"},
        }

    def pull(self, repository: str, number: int) -> dict:
        self.calls.append(("pull", repository, number))
        self._raise_if_needed()
        return {
            "number": self.pr_number,
            "state": "open",
            "draft": False,
            "merged": False,
            "html_url": f"https://github.com/{self.pr_repository}/pull/{self.pr_number}",
            "head": {"sha": self.commit_sha, "ref": "feature/verified"},
            "base": {"ref": "main"},
            "updated_at": "2026-09-18T20:02:00Z",
        }

    def check_runs(self, repository: str, sha: str) -> list[dict]:
        self.calls.append(("check_runs", repository, sha))
        self._raise_if_needed()
        return self.checks


@pytest.fixture()
def verification_client() -> Generator[TestClient, None, None]:
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


def _execution_with_source(client: TestClient, *, repository: str = "douglassnake/example") -> dict:
    project = client.post(
        "/projects",
        json={
            "slug": "github-verification-project",
            "name": "GitHub Verification Project",
            "status": "implementation",
            "next_action": "Verificar commit e checks",
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    source = client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "github",
            "external_id": repository,
            "url": f"https://github.com/{repository}",
            "label": "Código principal",
        },
    )
    assert source.status_code == 201

    context = client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "decision",
            "title": "Verificação externa",
            "content": "Checks verdes podem servir como evidência quando a regra for explícita.",
            "importance": 1.0,
            "source_type": "manual",
            "source_ref": "manual:github-verification",
        },
    )
    assert context.status_code == 201

    pack = client.post(
        "/agent-task-packs",
        json={
            "project_id": project_id,
            "objective": "Verificar execução por GitHub sem escrita externa",
            "acceptance_criteria": [
                "A suíte de testes deve passar",
                "A execução deve manter rastreabilidade",
            ],
            "constraints": ["GitHub somente leitura"],
            "suggested_areas": ["app/github_verification.py"],
            "profile": "minimal",
            "query": "github checks evidência rastreabilidade",
        },
    )
    assert pack.status_code == 201
    approved = client.post(f"/agent-task-packs/{pack.json()['id']}/approve")
    assert approved.status_code == 200

    handoff = client.post(
        f"/agent-task-packs/{approved.json()['id']}/handoffs",
        json={
            "executor_type": "codex",
            "allowed_actions": ["read_repository", "run_tests"],
        },
    )
    assert handoff.status_code == 201
    released = client.post(f"/agent-handoffs/{handoff.json()['id']}/release")
    assert released.status_code == 200

    execution = client.post(f"/agent-handoffs/{released.json()['id']}/execution")
    assert execution.status_code == 201
    return execution.json()


def _set_refs(
    client: TestClient,
    execution_id: str,
    *,
    commit_sha: str = "abc123456789",
    pr_url: str = "https://github.com/douglassnake/example/pull/7",
) -> dict:
    response = client.post(
        f"/agent-executions/{execution_id}/technical-refs",
        json={"commit_sha": commit_sha, "pr_url": pr_url},
    )
    assert response.status_code == 200
    return response.json()


def _install_reader(monkeypatch: pytest.MonkeyPatch, reader: FakeVerificationReader) -> None:
    def fake_verify(db, execution, pack, *, criterion_index=None, evidence_rule=None):
        return real_verify_execution_github(
            db,
            execution,
            pack,
            criterion_index=criterion_index,
            evidence_rule=evidence_rule,
            reader=reader,
        )

    monkeypatch.setattr(verification_routes, "verify_execution_github", fake_verify)


def test_green_verification_records_observation_but_does_not_infer_evidence(
    verification_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = verification_client
    execution = _execution_with_source(client)
    _set_refs(client, execution["id"])
    reader = FakeVerificationReader()
    _install_reader(monkeypatch, reader)

    response = client.post(
        f"/agent-executions/{execution['id']}/verify-github",
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["status"] == "verified"
    assert body["verification"]["repository"] == "douglassnake/example"
    assert body["verification"]["checks"]["checks_green"] is True
    assert body["verification"]["checks"]["count"] == 2
    assert body["evidence_attached"] is False
    assert body["evidence_reason"] == "no_explicit_evidence_rule"
    assert body["execution"]["criteria_coverage"]["passed"] == 0
    assert body["execution"]["criteria_coverage"]["pending"] == 2
    assert [call[0] for call in reader.calls] == ["pull", "commit", "check_runs"]

    events = client.get(f"/agent-executions/{execution['id']}/events")
    assert events.status_code == 200
    event_types = [event["event_type"] for event in events.json()]
    assert event_types == ["started", "technical_refs", "external_verification"]
    verification_event = events.json()[-1]
    assert verification_event["payload"]["provenance"] == "github_api_read_only"
    assert verification_event["payload"]["verified_at"]


def test_explicit_checks_green_rule_attaches_passed_evidence(
    verification_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = verification_client
    execution = _execution_with_source(client)
    _set_refs(client, execution["id"])
    reader = FakeVerificationReader()
    _install_reader(monkeypatch, reader)

    response = client.post(
        f"/agent-executions/{execution['id']}/verify-github",
        json={"criterion_index": 0, "evidence_rule": "checks_green"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["status"] == "verified"
    assert body["evidence_attached"] is True
    assert body["evidence_reason"] == "checks_green_rule_satisfied"
    assert body["execution"]["criteria"][0]["status"] == "passed"
    assert body["execution"]["criteria"][0]["evidence_type"] == "github_checks"
    assert body["execution"]["criteria_coverage"]["passed"] == 1
    assert body["execution"]["criteria_coverage"]["pending"] == 1

    events = client.get(f"/agent-executions/{execution['id']}/events").json()
    assert [event["event_type"] for event in events][-2:] == [
        "external_verification",
        "criterion_evidence",
    ]
    assert events[-1]["criterion_status"] == "passed"


def test_non_green_checks_never_generate_passed_evidence(
    verification_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = verification_client
    execution = _execution_with_source(client)
    _set_refs(client, execution["id"])
    reader = FakeVerificationReader(
        checks=[
            {
                "id": 200,
                "name": "pytest",
                "status": "completed",
                "conclusion": "failure",
                "details_url": "https://github.com/douglassnake/example/actions/runs/200",
            }
        ]
    )
    _install_reader(monkeypatch, reader)

    response = client.post(
        f"/agent-executions/{execution['id']}/verify-github",
        json={"criterion_index": 0, "evidence_rule": "checks_green"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["status"] == "verified"
    assert body["verification"]["checks"]["checks_green"] is False
    assert body["evidence_attached"] is False
    assert body["evidence_reason"] == "checks_not_green"
    assert body["execution"]["criteria"][0]["status"] == "pending"

    events = client.get(f"/agent-executions/{execution['id']}/events").json()
    assert events[-1]["event_type"] == "external_verification"
    assert not any(event["event_type"] == "criterion_evidence" for event in events)


def test_repository_mismatch_is_detected_before_reader_call(
    verification_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = verification_client
    execution = _execution_with_source(client)
    _set_refs(
        client,
        execution["id"],
        pr_url="https://github.com/other-owner/other-repo/pull/7",
    )
    reader = FakeVerificationReader()
    _install_reader(monkeypatch, reader)

    response = client.post(
        f"/agent-executions/{execution['id']}/verify-github",
        json={"criterion_index": 0, "evidence_rule": "checks_green"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["status"] == "mismatch"
    assert body["verification"]["reason"] == "pr_repository_not_linked_to_project"
    assert body["evidence_attached"] is False
    assert reader.calls == []


def test_api_failure_degrades_to_unavailable_and_404_to_not_found(
    verification_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = verification_client

    unavailable_execution = _execution_with_source(client)
    _set_refs(client, unavailable_execution["id"])
    unavailable_reader = FakeVerificationReader(
        error=GitHubAPIError("temporary failure", status_code=503)
    )
    _install_reader(monkeypatch, unavailable_reader)
    unavailable = client.post(
        f"/agent-executions/{unavailable_execution['id']}/verify-github",
        json={},
    )
    assert unavailable.status_code == 200
    assert unavailable.json()["verification"]["status"] == "unavailable"
    assert unavailable.json()["evidence_attached"] is False

    # Use another project slug by mutating the default helper's fixed slug would conflict,
    # so a fresh in-memory client is not available inside this test. Reuse the same execution
    # with another fake reader: the verification log is append-only and can record a later state.
    not_found_reader = FakeVerificationReader(
        error=GitHubAPIError("missing", status_code=404)
    )
    _install_reader(monkeypatch, not_found_reader)
    not_found = client.post(
        f"/agent-executions/{unavailable_execution['id']}/verify-github",
        json={},
    )
    assert not_found.status_code == 200
    assert not_found.json()["verification"]["status"] == "not_found"

    events = client.get(
        f"/agent-executions/{unavailable_execution['id']}/events"
    ).json()
    verification_statuses = [
        event["payload"]["status"]
        for event in events
        if event["event_type"] == "external_verification"
    ]
    assert verification_statuses == ["unavailable", "not_found"]


def test_evidence_mapping_must_be_complete_and_criterion_must_exist(
    verification_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = verification_client
    execution = _execution_with_source(client)
    _set_refs(client, execution["id"])
    reader = FakeVerificationReader()
    _install_reader(monkeypatch, reader)

    incomplete = client.post(
        f"/agent-executions/{execution['id']}/verify-github",
        json={"criterion_index": 0},
    )
    assert incomplete.status_code == 422
    assert reader.calls == []

    invalid = client.post(
        f"/agent-executions/{execution['id']}/verify-github",
        json={"criterion_index": 99, "evidence_rule": "checks_green"},
    )
    assert invalid.status_code == 422
    assert reader.calls == []
