#!/usr/bin/env bash
set -Eeuo pipefail

DB_CONTAINER="${DB_CONTAINER:-app-db-1}"
API_CONTAINER="${API_CONTAINER:-app-api-1}"
EXPECTED_LOG_DRIVER="${EXPECTED_LOG_DRIVER:-json-file}"
EXPECTED_LOG_MAX_SIZE="${SUPERCHAT_LOG_MAX_SIZE:-10m}"
EXPECTED_LOG_MAX_FILES="${SUPERCHAT_LOG_MAX_FILES:-5}"
MIN_FREE_PERCENT="${MIN_FREE_PERCENT:-15}"
APP_ROOT="${APP_ROOT:-/DATA/AppData/superchat}"
BACKUP_ROOT="${BACKUP_ROOT:-/DATA/Backup/superchat}"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

require_percent() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || die "MIN_FREE_PERCENT must be an integer from 1 to 99"
  ((value >= 1 && value <= 99)) || die "MIN_FREE_PERCENT must be an integer from 1 to 99"
}

command -v docker >/dev/null 2>&1 || die "docker command not found"
command -v df >/dev/null 2>&1 || die "df command not found"
require_percent "$MIN_FREE_PERCENT"

FAILURES=0

check_container_logging() {
  local container="$1"
  local running health driver max_size max_files log_path log_bytes

  running="$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)"
  if [[ "$running" != "true" ]]; then
    log "ERROR: container is not running: $container"
    FAILURES=$((FAILURES + 1))
    return
  fi

  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$container" 2>/dev/null || true)"
  driver="$(docker inspect -f '{{.HostConfig.LogConfig.Type}}' "$container" 2>/dev/null || true)"
  max_size="$(docker inspect -f '{{index .HostConfig.LogConfig.Config "max-size"}}' "$container" 2>/dev/null || true)"
  max_files="$(docker inspect -f '{{index .HostConfig.LogConfig.Config "max-file"}}' "$container" 2>/dev/null || true)"
  log_path="$(docker inspect -f '{{.LogPath}}' "$container" 2>/dev/null || true)"

  log "container=$container running=$running health=${health:-unknown} log_driver=${driver:-unset} max_size=${max_size:-unset} max_file=${max_files:-unset}"

  if [[ "$driver" != "$EXPECTED_LOG_DRIVER" ]]; then
    log "ERROR: $container log driver mismatch: expected=$EXPECTED_LOG_DRIVER observed=${driver:-unset}"
    FAILURES=$((FAILURES + 1))
  fi
  if [[ "$max_size" != "$EXPECTED_LOG_MAX_SIZE" ]]; then
    log "ERROR: $container max-size mismatch: expected=$EXPECTED_LOG_MAX_SIZE observed=${max_size:-unset}"
    FAILURES=$((FAILURES + 1))
  fi
  if [[ "$max_files" != "$EXPECTED_LOG_MAX_FILES" ]]; then
    log "ERROR: $container max-file mismatch: expected=$EXPECTED_LOG_MAX_FILES observed=${max_files:-unset}"
    FAILURES=$((FAILURES + 1))
  fi

  if [[ -n "$log_path" ]]; then
    if log_bytes="$(stat -c '%s' "$log_path" 2>/dev/null)"; then
      log "container=$container active_log_bytes=$log_bytes log_path=$log_path"
    else
      log "container=$container log_path=$log_path active_log_bytes=unavailable"
    fi
  fi
}

check_storage() {
  local path="$1"
  local line filesystem blocks used available capacity mountpoint used_percent free_percent

  [[ -e "$path" ]] || {
    log "ERROR: storage path does not exist: $path"
    FAILURES=$((FAILURES + 1))
    return
  }

  line="$(df -Pk "$path" | tail -1)"
  read -r filesystem blocks used available capacity mountpoint <<< "$line"
  used_percent="${capacity%%%}"
  [[ "$used_percent" =~ ^[0-9]+$ ]] || {
    log "ERROR: unable to parse filesystem usage for $path"
    FAILURES=$((FAILURES + 1))
    return
  }
  free_percent=$((100 - used_percent))
  log "storage=$path filesystem=$filesystem mount=$mountpoint used_percent=$used_percent free_percent=$free_percent available_kb=$available"

  if ((free_percent < MIN_FREE_PERCENT)); then
    log "ERROR: low free space on $path: free=${free_percent}% minimum=${MIN_FREE_PERCENT}%"
    FAILURES=$((FAILURES + 1))
  fi
}

log "storage-check: validating live Docker log rotation"
check_container_logging "$DB_CONTAINER"
check_container_logging "$API_CONTAINER"

log "storage-check: validating filesystem headroom"
check_storage "$APP_ROOT"
check_storage "$BACKUP_ROOT"

log "storage-check: Docker disk usage summary"
docker system df || true

if ((FAILURES > 0)); then
  die "storage-check failed with $FAILURES finding(s); do not recreate containers automatically"
fi

log "storage-check: completed successfully"
