from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[1]


def test_sensitive_settings_are_excluded_from_serialization() -> None:
    values = {
        "database_url": "postgresql+psycopg://user:DB_SECRET@localhost/db",
        "github_token": "READ_SECRET",
        "google_access_token": "GOOGLE_ACCESS_SECRET",
        "google_client_secret": "GOOGLE_CLIENT_SECRET",
        "google_refresh_token": "GOOGLE_REFRESH_SECRET",
        "executor_github_write_token": "PR_WRITE_SECRET",
        "executor_github_publish_token": "PUBLISH_SECRET",
    }
    settings = Settings(_env_file=None, **values)
    dumped = settings.model_dump()
    rendered = settings.model_dump_json()

    for field, secret in values.items():
        assert field not in dumped
        assert secret not in rendered
        assert getattr(settings, field) == secret


def test_integration_readiness_cli_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/integration_readiness.py"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(completed.stdout)
    assert report["status"] == "pass"
    assert all(check["ok"] for check in report["checks"].values())
    assert report["checks"]["adapters_fail_closed"]["available"] == {
        "isolated-local": False,
        "github-pr": False,
        "github-publish": False,
    }
