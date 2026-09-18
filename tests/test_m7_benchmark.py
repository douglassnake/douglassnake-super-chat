import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.benchmark import run_benchmark_dataset
from app.database import Base, get_db
from app.main import app
from app.retrieval_metrics import evaluate_retrieval


@pytest.fixture()
def evaluation_client() -> Generator[TestClient, None, None]:
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


def test_retrieval_metrics_are_deterministic() -> None:
    result = evaluate_retrieval(
        ["a", "b", "b", "c", None],
        ["a", "c"],
        k=2,
        selected_tokens=250,
        candidate_tokens=1000,
    )
    assert result.retrieved_unique == 3
    assert result.expected_unique == 2
    assert result.hits_at_k == 1
    assert result.precision_at_k == 0.5
    assert result.recall_at_k == 0.5
    assert result.coverage == 1.0
    assert result.context_efficiency == 0.25
    assert result.compression_ratio == 0.75


def test_evaluation_endpoint_scores_expected_source(evaluation_client: TestClient) -> None:
    project = evaluation_client.post(
        "/projects",
        json={
            "slug": "evaluation-project",
            "name": "Evaluation Project",
            "next_action": "Avaliar contexto",
        },
    ).json()
    project_id = project["id"]

    relevant = evaluation_client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "fact",
            "title": "Falha de CI",
            "content": "A pipeline de testes falhou e precisa de revisão no workflow.",
            "importance": 0.95,
            "source_type": "manual",
            "source_ref": "fixture:ci-failure",
        },
    )
    assert relevant.status_code == 201
    evaluation_client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "note",
            "title": "Outro assunto",
            "content": "Calendário editorial para uma campanha fictícia.",
            "importance": 0.3,
            "source_type": "manual",
            "source_ref": "fixture:unrelated",
        },
    )

    response = evaluation_client.post(
        "/evaluation/context",
        json={
            "project_id": project_id,
            "query": "pipeline testes falha workflow CI",
            "profile": "minimal",
            "expected_source_refs": ["fixture:ci-failure"],
            "k": 1,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "minimal"
    assert payload["latency_ms"] >= 0
    assert payload["metrics"]["precision_at_k"] == 1.0
    assert payload["metrics"]["recall_at_k"] == 1.0
    assert payload["metrics"]["coverage"] == 1.0
    assert payload["metrics"]["candidate_tokens"] >= payload["metrics"]["selected_tokens"]


def test_fixture_dataset_runs_without_external_services() -> None:
    path = Path("benchmarks/context_cases.json")
    dataset = json.loads(path.read_text(encoding="utf-8"))
    report = run_benchmark_dataset(dataset)

    assert report["dataset"] == "context-engine-baseline-v1"
    assert report["case_count"] == 4
    assert set(report["profiles"]) == {"minimal", "standard", "deep"}
    for case in report["results"]:
        metrics = case["metrics"]
        assert 0.0 <= metrics["precision_at_k"] <= 1.0
        assert 0.0 <= metrics["recall_at_k"] <= 1.0
        assert 0.0 <= metrics["coverage"] <= 1.0
        assert metrics["candidate_tokens"] >= metrics["selected_tokens"]
    pressure = next(case for case in report["results"] if case["name"] == "Token pressure minimal")
    assert pressure["metrics"]["recall_at_k"] == 1.0
    assert pressure["metrics"]["compression_ratio"] > 0
    assert pressure["metrics"]["context_efficiency"] < 1
    assert report["profiles"]["minimal"]["mean_recall_at_k"] > 0
    assert report["profiles"]["standard"]["mean_recall_at_k"] > 0
    assert report["profiles"]["deep"]["mean_recall_at_k"] > 0
