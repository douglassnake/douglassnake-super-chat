#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

BACKUP_ROOT="${BACKUP_ROOT:-/DATA/Backup/superchat/automatic}"
DB_CONTAINER="${DB_CONTAINER:-app-db-1}"
BACKUP_PREFIX="auto-superchat"
RESTORE_DB_PREFIX="superchat_restore_check"

REQUIRED_TABLES=(
  projects
  project_sources
  session_deltas
  agent_task_packs
  agent_handoffs
  agent_executions
  executor_requests
  worker_attempts
  git_change_approvals
  auth_sessions
  knowledge_entities
  project_relations
  graph_suggestion_batches
  knowledge_relations
)

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || die "docker command not found"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum command not found"
[[ -d "$BACKUP_ROOT" ]] || die "backup root does not exist: $BACKUP_ROOT"

RUNNING="$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || true)"
[[ "$RUNNING" == "true" ]] || die "database container is not running: $DB_CONTAINER"

LOCK_DIR="$BACKUP_ROOT/.restore-check.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  die "another restore check appears to be active: $LOCK_DIR"
fi

TEMP_DB=""
TEMP_DB_CREATED=0

cleanup() {
  local status=$?
  trap - EXIT INT TERM

  if [[ "$TEMP_DB_CREATED" == "1" && -n "$TEMP_DB" ]]; then
    log "restore-check: dropping disposable database $TEMP_DB"
    if ! docker exec "$DB_CONTAINER" sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$1"' sh "$TEMP_DB" >/dev/null 2>&1; then
      log "ERROR: failed to drop disposable database $TEMP_DB" >&2
      if [[ "$status" == "0" ]]; then
        status=1
      fi
    fi
  fi

  rmdir "$LOCK_DIR" 2>/dev/null || true
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

shopt -s nullglob
DUMPS=("$BACKUP_ROOT"/${BACKUP_PREFIX}-*.dump)
shopt -u nullglob
((${#DUMPS[@]} > 0)) || die "no automatic backups found in $BACKUP_ROOT"

mapfile -t DUMPS < <(printf '%s\n' "${DUMPS[@]}" | sort)
LATEST_DUMP="${DUMPS[$((${#DUMPS[@]} - 1))]}"
LATEST_NAME="$(basename "$LATEST_DUMP")"
LATEST_SHA="${LATEST_DUMP}.sha256"

[[ "$LATEST_NAME" =~ ^auto-superchat-[0-9]{8}T[0-9]{6}Z\.dump$ ]] || die "latest backup has an unexpected filename: $LATEST_NAME"
[[ -f "$LATEST_DUMP" && ! -L "$LATEST_DUMP" ]] || die "latest backup is not a regular file"
[[ -s "$LATEST_DUMP" ]] || die "latest backup is empty"
[[ -f "$LATEST_SHA" && ! -L "$LATEST_SHA" ]] || die "backup checksum sidecar is missing or invalid"

log "restore-check: validating SHA-256 for $LATEST_NAME"
(
  cd "$BACKUP_ROOT"
  sha256sum -c "$(basename "$LATEST_SHA")"
) >/dev/null

log "restore-check: validating custom-format archive"
docker exec -i "$DB_CONTAINER" pg_restore -l < "$LATEST_DUMP" >/dev/null

SOURCE_DB="$(docker exec "$DB_CONTAINER" sh -c 'printf "%s" "$POSTGRES_DB"')"
SOURCE_HEAD="$(docker exec "$DB_CONTAINER" sh -c 'psql -Atq -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version;"')"
[[ -n "$SOURCE_DB" ]] || die "source database name is empty"
[[ -n "$SOURCE_HEAD" ]] || die "source Alembic head is empty"

TEMP_DB="${RESTORE_DB_PREFIX}_$(date -u +%Y%m%dT%H%M%SZ)_$$"
[[ "$TEMP_DB" =~ ^superchat_restore_check_[A-Za-z0-9_]+$ ]] || die "generated disposable database name is invalid"
[[ "$TEMP_DB" != "$SOURCE_DB" ]] || die "refusing to use the primary database as restore target"

log "restore-check: creating disposable database $TEMP_DB"
docker exec "$DB_CONTAINER" sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$TEMP_DB"
TEMP_DB_CREATED=1

log "restore-check: restoring $LATEST_NAME into disposable database"
docker exec -i "$DB_CONTAINER" sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d "$1" --exit-on-error --no-owner --no-privileges' \
  sh "$TEMP_DB" < "$LATEST_DUMP"

RESTORED_HEAD="$(docker exec "$DB_CONTAINER" sh -c 'psql -Atq -U "$POSTGRES_USER" -d "$1" -c "SELECT version_num FROM alembic_version;"' sh "$TEMP_DB")"
[[ -n "$RESTORED_HEAD" ]] || die "restored Alembic head is empty"
[[ "$RESTORED_HEAD" == "$SOURCE_HEAD" ]] || die "restored Alembic head differs from production: restored=$RESTORED_HEAD production=$SOURCE_HEAD"

RESTORED_TABLES="$(docker exec "$DB_CONTAINER" sh -c 'psql -Atq -U "$POSTGRES_USER" -d "$1" -c "SELECT tablename FROM pg_tables WHERE schemaname = '\''public'\'' ORDER BY tablename;"' sh "$TEMP_DB")"

MISSING_TABLES=()
for table in "${REQUIRED_TABLES[@]}"; do
  if ! grep -Fxq "$table" <<< "$RESTORED_TABLES"; then
    MISSING_TABLES+=("$table")
  fi
done

if ((${#MISSING_TABLES[@]} > 0)); then
  die "restored database is missing critical tables: ${MISSING_TABLES[*]}"
fi

PROJECT_COUNT="$(docker exec "$DB_CONTAINER" sh -c 'psql -Atq -U "$POSTGRES_USER" -d "$1" -c "SELECT count(*) FROM projects;"' sh "$TEMP_DB")"
ENTITY_COUNT="$(docker exec "$DB_CONTAINER" sh -c 'psql -Atq -U "$POSTGRES_USER" -d "$1" -c "SELECT count(*) FROM knowledge_entities;"' sh "$TEMP_DB")"
[[ "$PROJECT_COUNT" =~ ^[0-9]+$ ]] || die "restored projects table is not readable"
[[ "$ENTITY_COUNT" =~ ^[0-9]+$ ]] || die "restored knowledge_entities table is not readable"

log "restore-check: verified backup=$LATEST_NAME alembic_head=$RESTORED_HEAD projects=$PROJECT_COUNT knowledge_entities=$ENTITY_COUNT"
log "restore-check: completed successfully"
