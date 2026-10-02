from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_semantic_edges_receive_directional_arrow_marker() -> None:
    script = (ROOT / "web" / "graph_suggestions.js").read_text(encoding="utf-8")

    assert 'svg.querySelectorAll(".graph-edge.semantic")' in script
    assert 'id: "graph-semantic-arrow"' in script
    assert 'line.setAttribute("marker-end", "url(#graph-semantic-arrow)")' in script
    assert 'line.classList.add("directed")' in script
    assert 'line.dataset.arrowDecorated = "true"' in script


def test_arrow_tip_stops_before_target_node_instead_of_hiding_under_it() -> None:
    script = (ROOT / "web" / "graph_suggestions.js").read_text(encoding="utf-8")

    assert "function targetNodeForLine(svg, x, y)" in script
    assert "function visualNodeRadius(node)" in script
    assert 'getComputedStyle(circle).getPropertyValue("r")' in script
    assert "const offset = targetRadius + 4" in script
    assert 'line.setAttribute("x2", String(x2 - (dx / length) * offset))' in script
    assert 'line.setAttribute("y2", String(y2 - (dy / length) * offset))' in script


def test_semantic_edge_direction_reapplies_after_graph_rerender() -> None:
    script = (ROOT / "web" / "graph_suggestions.js").read_text(encoding="utf-8")

    assert 'const graphSvg = $("#knowledge-graph-svg")' in script
    assert "const semanticEdgeObserver = new MutationObserver" in script
    assert "semanticEdgeObserver.observe(graphSvg, { childList: true, subtree: true })" in script
    assert "window.setTimeout(decorateSemanticEdges, 0)" in script
