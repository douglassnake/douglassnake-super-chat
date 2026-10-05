from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ops_restore_check.sh"


def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_restore_check_script_has_valid_bash_syntax() -> None:
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run([bash, "-n", str(SCRIPT)], check=True)


def test_restore_check_is_fail_closed_and_integrity_checked() -> None:
    script = script_text()

    assert "set -Eeuo pipefail" in script
    assert "umask 077" in script
    assert "sha256sum -c" in script
    assert "pg_restore -l" in script
    assert "--exit-on-error" in script
    assert ".restore-check.lock" in script
    assert '[[ -s "$LATEST_DUMP" ]]' in script


def test_restore_target_is_disposable_and_primary_database_is_protected() -> None:
    script = script_text()

    assert 'RESTORE_DB_PREFIX="superchat_restore_check"' in script
    assert '[[ "$TEMP_DB" != "$SOURCE_DB" ]]' in script
    assert "createdb" in script
    assert "dropdb" in script
    assert 'dropdb -U "$POSTGRES_USER" --if-exists "$1"' in script
    assert "DROP DATABASE superchat" not in script
    assert "dropdb -U \"$POSTGRES_USER\" \"$POSTGRES_DB\"" not in script


def test_disposable_database_is_removed_on_exit() -> None:
    script = script_text()

    assert "cleanup()" in script
    assert "trap cleanup EXIT" in script
    assert 'TEMP_DB_CREATED=0' in script
    assert 'TEMP_DB_CREATED=1' in script
    assert 'if [[ "$TEMP_DB_CREATED" == "1" && -n "$TEMP_DB" ]]' in script


def test_restored_database_checks_schema_and_core_data() -> None:
    script = script_text()

    assert "SOURCE_HEAD" in script
    assert "RESTORED_HEAD" in script
    assert '[[ "$RESTORED_HEAD" == "$SOURCE_HEAD" ]]' in script
    for table in (
        "projects",
        "project_sources",
        "session_deltas",
        "auth_sessions",
        "knowledge_entities",
        "project_relations",
        "graph_suggestion_batches",
        "knowledge_relations",
    ):
        assert table in script
    assert 'SELECT count(*) FROM projects;' in script
    assert 'SELECT count(*) FROM knowledge_entities;' in script


def test_disposable_restore_runs_integration_readiness_inside_api_container() -> None:
    script = script_text()

    assert 'API_CONTAINER="${API_CONTAINER:-app-api-1}"' in script
    assert 'API_RUNNING=' in script
    assert 'RESTORE_CHECK_DB="$TEMP_DB"' in script
    assert 'scripts/integration_readiness.py", "--database"' in script
    assert 'restore-check: integration readiness passed' in script
    assert 'make_url(env["DATABASE_URL"])' in script
    assert 'env["SECRET_BACKEND"] = "settings"' in script
    assert 'env.pop("SECRET_DIR", None)' in script


def test_database_credentials_are_not_exposed_as_host_arguments_or_logs() -> None:
    script = script_text()

    assert "POSTGRES_PASSWORD" in script
    assert "PGPASSWORD" in script
    assert "-e DATABASE_URL=" not in script
    assert "--password" not in script
    assert 'printf "%s" "$POSTGRES_PASSWORD"' not in script
    assert 'echo "$POSTGRES_PASSWORD"' not in script
