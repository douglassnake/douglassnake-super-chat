#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.core.config import Settings
from app.executor_control import EXECUTOR_FORBIDDEN_ACTIONS
from app.github_pr_executor import GitHubPullRequestExecutorAdapter
from app.github_publish_executor import GitHubBranchPublishExecutorAdapter
from app.isolated_executor import IsolatedLocalExecutorAdapter
from app.main import app


EXPECTED_API_VERSION = "0.8.15"
SENSITIVE_SETTINGS = {
    "database_url",
    "github_token",
    "google_access_token",
    "google_client_secret",
    "google_refresh_token",
    "executor_github_write_token",
    "executor_github_publish_token",
}
REQUIRED_MIGRATED_TABLES = {
    "projects",
    "project_sources",
    "session_deltas",
    "agent_task_packs",
    "agent_handoffs",
    "agent_executions",
    "executor_requests",
    "worker_attempts",
    "git_change_approvals",
}


def _alembic_scripts() -> ScriptDirectory:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def _check_migration_graph() -> dict[str, Any]:
    scripts = _alembic_scripts()
    heads = list(scripts.get_heads())
    bases = list(scripts.get_bases())
    revisions = list(scripts.walk_revisions())
    merge_revisions = [revision.revision for revision in revisions if isinstance(revision.down_revision, tuple)]
    return {
        "ok": len(heads) == 1 and len(bases) == 1 and not merge_revisions and bool(revisions),
        "head": heads[0] if len(heads) == 1 else heads,
        "base": bases[0] if len(bases) == 1 else bases,
        "revision_count": len(revisions),
        "merge_revisions": merge_revisions,
    }


def _check_database_migration() -> dict[str, Any]:
    settings = Settings()
    scripts = _alembic_scripts()
    heads = list(scripts.get_heads())
    expected_head = heads[0] if len(heads) == 1 else None
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            tables = set(inspect(connection).get_table_names())
    finally:
        engine.dispose()
    missing_tables = sorted(REQUIRED_MIGRATED_TABLES - tables)
    return {
        "ok": expected_head is not None and current == expected_head and not missing_tables,
        "expected_head": expected_head,
        "database_head": current,
        "missing_tables": missing_tables,
    }


def _check_fail_closed_defaults() -> dict[str, Any]:
    fields = Settings.model_fields
    expected = {
        "executor_isolated_enabled": False,
        "executor_github_write_enabled": False,
        "executor_github_publish_enabled": False,
        "executor_worktree_root": None,
        "executor_git_staging_root": None,
        "executor_git_publish_remote": None,
        "executor_github_write_repository": None,
        "executor_github_publish_repository": None,
    }
    observed = {name: fields[name].default for name in expected}
    return {"ok": observed == expected, "observed": observed}


def _check_secret_serialization() -> dict[str, Any]:
    sentinels = {
        "database_url": "postgresql+psycopg://user:DB_SECRET@localhost/db",
        "github_token": "READ_SECRET_1",
        "google_access_token": "GOOGLE_ACCESS_SECRET_2",
        "google_client_secret": "GOOGLE_CLIENT_SECRET_3",
        "google_refresh_token": "GOOGLE_REFRESH_SECRET_4",
        "executor_github_write_token": "PR_WRITE_SECRET_5",
        "executor_github_publish_token": "PUBLISH_SECRET_6",
    }
    settings = Settings(_env_file=None, **sentinels)
    dumped = settings.model_dump()
    rendered = settings.model_dump_json()
    leaked_fields = sorted(SENSITIVE_SETTINGS.intersection(dumped))
    leaked_values = sorted(value for value in sentinels.values() if value in rendered)
    accessible = all(getattr(settings, key) == value for key, value in sentinels.items())
    return {
        "ok": not leaked_fields and not leaked_values and accessible,
        "serialized_sensitive_fields": leaked_fields,
        "serialized_secret_count": len(leaked_values),
        "in_memory_access_preserved": accessible,
    }


def _check_adapters_fail_closed() -> dict[str, Any]:
    settings = Settings(_env_file=None)
    isolated = IsolatedLocalExecutorAdapter.from_settings(settings)
    github_pr = GitHubPullRequestExecutorAdapter.from_settings(settings)
    github_publish = GitHubBranchPublishExecutorAdapter.from_settings(settings)
    states = {
        "isolated-local": bool(isolated.available),
        "github-pr": bool(github_pr.available),
        "github-publish": bool(github_publish.available),
    }
    return {"ok": not any(states.values()), "available": states}


def _check_policy_boundary() -> dict[str, Any]:
    required_forbidden = {"merge", "deploy", "publish"}
    missing = sorted(required_forbidden - set(EXECUTOR_FORBIDDEN_ACTIONS))
    return {"ok": not missing, "missing_forbidden_actions": missing}


def _check_version() -> dict[str, Any]:
    return {
        "ok": app.version == EXPECTED_API_VERSION,
        "expected": EXPECTED_API_VERSION,
        "observed": app.version,
    }


def build_report(*, check_database: bool = False) -> dict[str, Any]:
    checks = {
        "migration_graph": _check_migration_graph(),
        "fail_closed_defaults": _check_fail_closed_defaults(),
        "secret_serialization": _check_secret_serialization(),
        "adapters_fail_closed": _check_adapters_fail_closed(),
        "policy_boundary": _check_policy_boundary(),
        "api_version": _check_version(),
    }
    if check_database:
        checks["database_migration"] = _check_database_migration()
    return {
        "status": "pass" if all(item["ok"] for item in checks.values()) else "fail",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Super Chat integration-readiness guardrails")
    parser.add_argument(
        "--database",
        action="store_true",
        help="also validate that the configured database is upgraded to the single Alembic head",
    )
    args = parser.parse_args()
    report = build_report(check_database=args.database)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
