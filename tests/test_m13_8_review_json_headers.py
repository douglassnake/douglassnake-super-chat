"""Regression for M13.8 browser request header merging."""
from pathlib import Path


def test_api_keeps_json_content_type_when_csrf_headers_are_supplied():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(
        encoding="utf-8"
    )
    api_start = source.index("async function api(path, options = {})")
    api_end = source.index("\nfunction showToast(", api_start)
    helper = source[api_start:api_end]
    assert helper.index("...options,") < helper.index(
        'headers: { "Content-Type": "application/json", ...(options.headers || {}) }'
    )
    assert 'headers: { "x-csrf-token": csrfToken }' in source
    assert 'body: JSON.stringify({' in source
