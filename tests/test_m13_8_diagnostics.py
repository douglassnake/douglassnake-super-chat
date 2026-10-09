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
