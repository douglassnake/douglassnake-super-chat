from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

BACKUP_FORMAT_VERSION = 1
CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
REQUIRED_TABLES = {
    "projects",
    "project_sources",
    "session_deltas",
    "agent_task_packs",
    "agent_handoffs",
    "agent_executions",
    "executor_requests",
    "worker_attempts",
    "git_change_approvals",
    "auth_sessions",
}


class RecoveryError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _connection_parts(database_url: str) -> dict[str, Any]:
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise RecoveryError("invalid database URL") from exc
    if not url.drivername.startswith("postgresql"):
        raise RecoveryError("backup/restore supports PostgreSQL only")
    if not url.database or not url.username:
        raise RecoveryError("database URL must include database name and username")
    return {
        "database": url.database,
        "username": url.username,
        "password": url.password or "",
        "host": url.host or "localhost",
        "port": int(url.port or 5432),
        "sslmode": str(url.query.get("sslmode") or ""),
    }


def _tool_env(database_url: str) -> tuple[dict[str, str], list[str]]:
    parts = _connection_parts(database_url)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PGHOST": parts["host"],
        "PGPORT": str(parts["port"]),
        "PGUSER": parts["username"],
        "PGDATABASE": parts["database"],
        "PGPASSWORD": parts["password"],
    }
    if parts["sslmode"]:
        env["PGSSLMODE"] = parts["sslmode"]
    args = ["-U", parts["username"], "-d", parts["database"]]
    return env, args


def _tool_command(
    tool: str,
    database_url: str,
    *,
    postgres_container: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    env, db_args = _tool_env(database_url)
    if postgres_container:
        container = str(postgres_container).strip()
        if not CONTAINER_NAME.fullmatch(container):
            raise RecoveryError("invalid PostgreSQL container identifier")
        docker = shutil.which("docker")
        if docker is None:
            raise RecoveryError("docker executable is unavailable")
        # `-e PGPASSWORD` forwards the variable from subprocess env without
        # putting the password itself in argv/process listings.
        return [docker, "exec", "-i", "-e", "PGPASSWORD", container, tool, *db_args], env
    executable = shutil.which(tool)
    if executable is None:
        raise RecoveryError(f"{tool} executable is unavailable")
    return [executable, *db_args], env


def _database_metadata(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            tables = sorted(inspect(connection).get_table_names(schema="public"))
    except Exception as exc:
        raise RecoveryError("unable to inspect source PostgreSQL database") from exc
    finally:
        engine.dispose()
    return {"alembic_head": str(head), "tables": tables}


def create_postgres_backup(
    database_url: str,
    output_root: str | Path,
    *,
    postgres_container: str | None = None,
) -> Path:
    root = Path(output_root).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise RecoveryError("backup output root is not a directory")

    suffix = secrets.token_hex(4)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_dir = root / f"backup-{stamp}-{suffix}"
    backup_dir.mkdir(mode=0o700)
    dump_path = backup_dir / "database.dump"
    temp_dump = backup_dir / ".database.dump.partial"
    manifest_path = backup_dir / "manifest.json"

    metadata = _database_metadata(database_url)
    command, env = _tool_command("pg_dump", database_url, postgres_container=postgres_container)
    command.extend(["--format=custom", "--no-owner", "--no-privileges"])

    try:
        with temp_dump.open("wb") as output:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
                timeout=900,
            )
        if completed.returncode != 0:
            raise RecoveryError("pg_dump failed; backup was not created")
        if temp_dump.stat().st_size <= 0:
            raise RecoveryError("pg_dump produced an empty backup")
        temp_dump.chmod(0o600)
        temp_dump.replace(dump_path)
        checksum = sha256_file(dump_path)
        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at": utcnow().isoformat(),
            "dump_file": dump_path.name,
            "sha256": checksum,
            "bytes": dump_path.stat().st_size,
            "alembic_head": metadata["alembic_head"],
            "table_count": len(metadata["tables"]),
            "required_tables_present": sorted(REQUIRED_TABLES.intersection(metadata["tables"])),
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
        return backup_dir
    except Exception:
        temp_dump.unlink(missing_ok=True)
        if not dump_path.exists() and not manifest_path.exists():
            try:
                backup_dir.rmdir()
            except OSError:
                pass
        raise


def load_and_verify_manifest(backup_dir: str | Path) -> tuple[dict[str, Any], Path]:
    root = Path(backup_dir).expanduser().resolve(strict=True)
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RecoveryError("backup manifest is missing or invalid")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("backup manifest cannot be parsed") from exc
    if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise RecoveryError("unsupported backup manifest version")
    dump_name = str(manifest.get("dump_file") or "")
    if dump_name != "database.dump":
        raise RecoveryError("backup manifest contains an unexpected dump filename")
    dump_path = root / dump_name
    if dump_path.is_symlink() or not dump_path.is_file():
        raise RecoveryError("backup dump is missing or invalid")
    expected_bytes = int(manifest.get("bytes") or -1)
    expected_hash = str(manifest.get("sha256") or "")
    if dump_path.stat().st_size != expected_bytes:
        raise RecoveryError("backup dump size does not match manifest")
    actual_hash = sha256_file(dump_path)
    if not expected_hash or not secrets.compare_digest(actual_hash, expected_hash):
        raise RecoveryError("backup dump SHA-256 does not match manifest")
    return manifest, dump_path


def _assert_empty_target(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names(schema="public")
    except Exception as exc:
        raise RecoveryError("unable to inspect restore target") from exc
    finally:
        engine.dispose()
    if tables:
        raise RecoveryError("restore target must be an empty/disposable database")


def restore_postgres_backup(
    backup_dir: str | Path,
    target_database_url: str,
    *,
    confirm_empty_target: bool,
    postgres_container: str | None = None,
) -> dict[str, Any]:
    if not confirm_empty_target:
        raise RecoveryError("explicit --confirm-empty-target is required")
    manifest, dump_path = load_and_verify_manifest(backup_dir)
    _assert_empty_target(target_database_url)
    command, env = _tool_command("pg_restore", target_database_url, postgres_container=postgres_container)
    command.extend(["--exit-on-error", "--no-owner", "--no-privileges"])

    try:
        with dump_path.open("rb") as source:
            completed = subprocess.run(
                command,
                stdin=source,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
                timeout=900,
            )
    except OSError as exc:
        raise RecoveryError("unable to execute pg_restore") from exc
    if completed.returncode != 0:
        raise RecoveryError(
            "pg_restore failed after restore started; discard the target database and retry from a verified backup"
        )

    engine = create_engine(target_database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            restored_head = str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
            tables = set(inspect(connection).get_table_names(schema="public"))
    except Exception as exc:
        raise RecoveryError("restored database cannot be verified") from exc
    finally:
        engine.dispose()

    if restored_head != str(manifest.get("alembic_head") or ""):
        raise RecoveryError("restored Alembic head differs from backup manifest")
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise RecoveryError(f"restored database is missing critical tables: {', '.join(missing)}")
    return {
        "status": "verified",
        "alembic_head": restored_head,
        "sha256": manifest["sha256"],
        "bytes": manifest["bytes"],
        "critical_tables": sorted(REQUIRED_TABLES),
    }
