#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

BACKUP_ROOT="${BACKUP_ROOT:-/DATA/Backup/superchat/automatic}"
DB_CONTAINER="${DB_CONTAINER:-app-db-1}"
KEEP_COUNT="${KEEP_COUNT:-14}"
SECONDARY_ROOT="${SECONDARY_ROOT:-}"
SECONDARY_KEEP_COUNT="${SECONDARY_KEEP_COUNT:-$KEEP_COUNT}"
BACKUP_PREFIX="auto-superchat"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

require_positive_integer() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "$name must be a positive integer"
}

prune_root() {
  local root="$1"
  local keep="$2"
  local -a files=()
  local remove_count index

  [[ -d "$root" ]] || return 0
  shopt -s nullglob
  files=("$root"/${BACKUP_PREFIX}-*.dump)
  shopt -u nullglob
  ((${#files[@]} > keep)) || return 0

  mapfile -t files < <(printf '%s\n' "${files[@]}" | sort)
  remove_count=$((${#files[@]} - keep))
  for ((index = 0; index < remove_count; index++)); do
    local dump="${files[$index]}"
    log "retention: removing $(basename "$dump")"
    rm -f -- "$dump" "${dump}.sha256"
  done
}

require_positive_integer KEEP_COUNT "$KEEP_COUNT"
require_positive_integer SECONDARY_KEEP_COUNT "$SECONDARY_KEEP_COUNT"
command -v docker >/dev/null 2>&1 || die "docker command not found"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum command not found"

mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT" 2>/dev/null || true

LOCK_DIR="$BACKUP_ROOT/.backup.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  die "another backup run appears to be active: $LOCK_DIR"
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL_DUMP="$BACKUP_ROOT/${BACKUP_PREFIX}-${TIMESTAMP}.dump"
TEMP_DUMP="$BACKUP_ROOT/.${BACKUP_PREFIX}-${TIMESTAMP}.dump.tmp"
TEMP_SHA="$BACKUP_ROOT/.${BACKUP_PREFIX}-${TIMESTAMP}.dump.sha256.tmp"

cleanup() {
  rm -f -- "$TEMP_DUMP" "$TEMP_SHA"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

RUNNING="$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || true)"
[[ "$RUNNING" == "true" ]] || die "database container is not running: $DB_CONTAINER"

log "backup: starting PostgreSQL dump from $DB_CONTAINER"
docker exec "$DB_CONTAINER" \
  sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$TEMP_DUMP"

[[ -s "$TEMP_DUMP" ]] || die "pg_dump produced an empty backup"

log "backup: validating custom-format archive"
docker exec -i "$DB_CONTAINER" pg_restore -l < "$TEMP_DUMP" >/dev/null

DUMP_SHA="$(sha256sum "$TEMP_DUMP" | awk '{print $1}')"
printf '%s  %s\n' "$DUMP_SHA" "$(basename "$FINAL_DUMP")" > "$TEMP_SHA"

mv "$TEMP_DUMP" "$FINAL_DUMP"
mv "$TEMP_SHA" "${FINAL_DUMP}.sha256"
chmod 600 "$FINAL_DUMP" "${FINAL_DUMP}.sha256" 2>/dev/null || true
log "backup: primary complete $(basename "$FINAL_DUMP") sha256=$DUMP_SHA"

if [[ -n "$SECONDARY_ROOT" ]]; then
  [[ "$SECONDARY_ROOT" != "$BACKUP_ROOT" ]] || die "SECONDARY_ROOT must differ from BACKUP_ROOT"
  mkdir -p "$SECONDARY_ROOT"
  chmod 700 "$SECONDARY_ROOT" 2>/dev/null || true

  SECONDARY_FINAL="$SECONDARY_ROOT/$(basename "$FINAL_DUMP")"
  SECONDARY_TEMP="$SECONDARY_ROOT/.$(basename "$FINAL_DUMP").tmp"
  cp -- "$FINAL_DUMP" "$SECONDARY_TEMP"
  SECONDARY_SHA="$(sha256sum "$SECONDARY_TEMP" | awk '{print $1}')"
  [[ "$SECONDARY_SHA" == "$DUMP_SHA" ]] || {
    rm -f -- "$SECONDARY_TEMP"
    die "secondary backup checksum mismatch"
  }
  mv "$SECONDARY_TEMP" "$SECONDARY_FINAL"
  printf '%s  %s\n' "$DUMP_SHA" "$(basename "$SECONDARY_FINAL")" > "${SECONDARY_FINAL}.sha256"
  chmod 600 "$SECONDARY_FINAL" "${SECONDARY_FINAL}.sha256" 2>/dev/null || true
  log "backup: secondary copy verified at $SECONDARY_FINAL"
fi

prune_root "$BACKUP_ROOT" "$KEEP_COUNT"
if [[ -n "$SECONDARY_ROOT" ]]; then
  prune_root "$SECONDARY_ROOT" "$SECONDARY_KEEP_COUNT"
fi

log "backup: completed successfully"
printf '%s\n' "$FINAL_DUMP"
