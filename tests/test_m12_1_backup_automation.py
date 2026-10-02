from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ops_backup.sh"


def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_backup_script_has_valid_bash_syntax() -> None:
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run([bash, "-n", str(SCRIPT)], check=True)


def test_backup_script_is_fail_closed_and_integrity_checked() -> None:
    script = script_text()

    assert "set -Eeuo pipefail" in script
    assert "umask 077" in script
    assert "pg_dump" in script
    assert "pg_restore -l" in script
    assert "sha256sum" in script
    assert ".backup.lock" in script
    assert "[[ -s \"$TEMP_DUMP\" ]]" in script


def test_retention_only_targets_automatic_backup_namespace() -> None:
    script = script_text()

    assert 'BACKUP_PREFIX="auto-superchat"' in script
    assert 'files=("$root"/${BACKUP_PREFIX}-*.dump)' in script
    assert 'rm -f -- "$dump" "${dump}.sha256"' in script
    assert "rm -rf" not in script
    assert "pre-m11" not in script


def test_secondary_copy_is_optional_and_checksum_verified() -> None:
    script = script_text()

    assert 'SECONDARY_ROOT="${SECONDARY_ROOT:-}"' in script
    assert '[[ "$SECONDARY_ROOT" != "$BACKUP_ROOT" ]]' in script
    assert '[[ "$SECONDARY_SHA" == "$DUMP_SHA" ]]' in script
    assert 'prune_root "$SECONDARY_ROOT" "$SECONDARY_KEEP_COUNT"' in script


def test_database_credentials_stay_inside_database_container() -> None:
    script = script_text()

    assert "POSTGRES_PASSWORD" in script
    assert "PGPASSWORD" in script
    assert "--password" not in script
    assert "DATABASE_URL" not in script
