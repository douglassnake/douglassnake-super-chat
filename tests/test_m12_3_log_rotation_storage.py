from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ops_storage_check.sh"
PRODUCTION_COMPOSE = ROOT / "docker-compose.production.yml"


def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def compose_text() -> str:
    return PRODUCTION_COMPOSE.read_text(encoding="utf-8")


def test_storage_script_has_valid_bash_syntax() -> None:
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run([bash, "-n", str(SCRIPT)], check=True)


def test_production_compose_keeps_bounded_json_logs_for_db_and_api() -> None:
    compose = compose_text()

    assert compose.count("driver: json-file") >= 2
    assert compose.count("max-size: ${SUPERCHAT_LOG_MAX_SIZE:-10m}") >= 2
    assert compose.count('max-file: "${SUPERCHAT_LOG_MAX_FILES:-5}"') >= 2


def test_storage_audit_checks_live_log_options_and_both_containers() -> None:
    script = script_text()

    assert 'DB_CONTAINER="${DB_CONTAINER:-app-db-1}"' in script
    assert 'API_CONTAINER="${API_CONTAINER:-app-api-1}"' in script
    assert ".HostConfig.LogConfig.Type" in script
    assert 'index .HostConfig.LogConfig.Config "max-size"' in script
    assert 'index .HostConfig.LogConfig.Config "max-file"' in script
    assert 'check_container_logging "$DB_CONTAINER"' in script
    assert 'check_container_logging "$API_CONTAINER"' in script


def test_storage_audit_has_disk_headroom_guardrail() -> None:
    script = script_text()

    assert 'MIN_FREE_PERCENT="${MIN_FREE_PERCENT:-15}"' in script
    assert 'APP_ROOT="${APP_ROOT:-/DATA/AppData/superchat}"' in script
    assert 'BACKUP_ROOT="${BACKUP_ROOT:-/DATA/Backup/superchat}"' in script
    assert 'check_storage "$APP_ROOT"' in script
    assert 'check_storage "$BACKUP_ROOT"' in script
    assert "free_percent < MIN_FREE_PERCENT" in script


def test_storage_audit_never_restarts_or_removes_containers() -> None:
    script = script_text()

    forbidden = [
        "docker restart",
        "docker stop",
        "docker rm",
        "docker compose up",
        "docker compose down",
        "docker container prune",
        "docker system prune",
    ]
    for command in forbidden:
        assert command not in script

    assert "do not recreate containers automatically" in script
