from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_graph_suggestion_modal_prevents_horizontal_overflow() -> None:
    css = (ROOT / "web" / "graph_suggestions.css").read_text(encoding="utf-8")

    assert ".graph-suggestion-dialog { width: min(760px, calc(100vw - 30px)); overflow-x: hidden; }" in css
    assert "width: 100%; max-width: 100%; min-width: 0;" in css
    assert "overflow-y: auto; overflow-x: hidden;" in css
    assert "word-break: break-word;" in css


def test_graph_suggestion_evidence_has_visual_emphasis_and_mobile_actions() -> None:
    css = (ROOT / "web" / "graph_suggestions.css").read_text(encoding="utf-8")

    assert ".graph-suggestion-body small:first-of-type" in css
    assert "border-left: 2px solid" in css
    assert "@media (max-width: 620px)" in css
    assert ".graph-suggestion-dialog .modal-actions .button { flex: 1 1 100%; width: 100%; }" in css
