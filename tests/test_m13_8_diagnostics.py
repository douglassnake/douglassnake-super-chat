"""M13.8: regressões de diagnósticos e mensagens de revisão."""
from pathlib import Path
from app import task_reconciliation as module


def test_read_only_reconciliation_has_portuguese_explanations():
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "Uma execução posterior aprovada no mesmo workflow e branch" in source
    assert "Evento de origem não está disponível no histórico sincronizado." in source
    assert "Tarefa sem referência de evento GitHub válida." in source
    assert "diagnostic_count" in source
    assert '"changes_applied": 0' in source


def test_interface_escapes_diagnostic_messages():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "Array.isArray(data.diagnostics)" in source
    assert "escapeHtml(item.reason)" in source
    assert "Evidência insuficiente" in source


def test_diagnostic_classification_on_real_evaluator():
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    from uuid import uuid4

    project = SimpleNamespace(id=uuid4(), slug="radar-guarda-mor")
    failure = SimpleNamespace(
        id=uuid4(), project_id=project.id, source_type="github",
        event_type="github.workflow_run", title="Action Coletar calibracao V5: failure",
        occurred_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        metadata_json={"repository": "douglassnake/radar-guardamor", "head_branch": "main", "conclusion": "failure", "status": "completed"},
        url="https://github.com/douglassnake/radar-guardamor/actions/runs/100",
    )
    task = SimpleNamespace(
        id=uuid4(), project_id=project.id, status="todo",
        title="Investigar novas falhas de CI", source_ref=f"event:{failure.id}",
    )

    class Results:
        def __init__(self, values): self.values = values
        def all(self): return self.values

    class DB:
        def __init__(self, tasks, runs): self.values = [[project], tasks, runs]; self.i = 0
        def scalars(self, statement):
            values = self.values[self.i]
            self.i += 1
            return Results(values)

    def inspect(tasks, runs):
        report = module.collect_ci_reconciliation_hints(DB(tasks, runs), project_slug=project.slug)
        assert report["changes_applied"] == 0
        return report

    initial = inspect([task], [failure])
    assert initial["diagnostics"][0]["classification"] == "open"
    missing = inspect([SimpleNamespace(**{**vars(task), "source_ref": None})], [failure])
    assert missing["diagnostics"][0]["classification"] == "insufficient_evidence"
    recovered = SimpleNamespace(**{**vars(failure),
        "id": uuid4(), "title": "Action Coletar calibracao V5: success",
        "occurred_at": failure.occurred_at + timedelta(minutes=5),
        "metadata_json": {**failure.metadata_json, "conclusion": "success"},
        "url": "https://github.com/douglassnake/radar-guardamor/actions/runs/101"})
    report = inspect([task], [failure, recovered])
    assert report["suggestion_count"] == 1
    assert report["diagnostic_count"] == 0
    regression = SimpleNamespace(**{**vars(recovered), "id": uuid4(),
        "title": "Action Coletar calibracao V5: failure",
        "occurred_at": recovered.occurred_at + timedelta(minutes=5),
        "metadata_json": {**recovered.metadata_json, "conclusion": "failure"}})
    assert inspect([task], [failure, recovered, regression])["diagnostics"][0]["classification"] == "open"
