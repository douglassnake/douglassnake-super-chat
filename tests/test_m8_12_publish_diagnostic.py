from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_m8_10_apply_approved_change import apply_client
from tests.test_m8_12_publish_branch import _publish_request, _setup_publish_candidate


def test_publish_branch_diagnostic_envelope(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_publish_candidate(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="publish-diagnostic-m8-12",
        branch_name="superchat/publish-diagnostic-m8-12",
    )
    created = _publish_request(apply_client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert apply_client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = apply_client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    print("M8_12_DIAGNOSTIC=" + json.dumps(body, ensure_ascii=False, sort_keys=True, default=str))
    assert body["status"] == "completed", body
