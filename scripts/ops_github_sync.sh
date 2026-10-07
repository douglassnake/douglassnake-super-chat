#!/usr/bin/env bash
set -Eeuo pipefail

API_CONTAINER="${API_CONTAINER:-app-api-1}"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || die "docker command not found"

RUNNING="$(docker inspect -f '{{.State.Running}}' "$API_CONTAINER" 2>/dev/null || true)"
[[ "$RUNNING" == "true" ]] || die "API container is not running: $API_CONTAINER"

exec docker exec -w /app "$API_CONTAINER"   python scripts/ops_github_sync.py "$@"
