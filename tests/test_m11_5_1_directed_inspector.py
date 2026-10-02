from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_semantic_inspector_relations_show_edge_direction() -> None:
    script = (ROOT / "web" / "graph_suggestions.js").read_text(encoding="utf-8")

    assert "async function directionalizeInspectorRelations()" in script
    assert "edge.semantic && (edge.source === selectedId || edge.target === selectedId)" in script
    assert "? `${relationText} → ${otherLabel}`" in script
    assert ": `← ${relationText} · ${otherLabel}`" in script


def test_inspector_direction_refresh_is_non_blocking_and_observed() -> None:
    script = (ROOT / "web" / "graph_suggestions.js").read_text(encoding="utf-8")

    assert 'const graphInspector = $("#graph-inspector")' in script
    assert "new MutationObserver" in script
    assert 'button.dataset.directionApplied = "true"' in script
    assert "Direction is presentation-only" in script
