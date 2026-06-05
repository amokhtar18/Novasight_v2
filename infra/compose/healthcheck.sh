#!/usr/bin/env bash
# Probe each service of the local stack from the HOST, using the ports defined in the
# repo-root .env (single source of truth). Exits non-zero if any check fails.
set -euo pipefail

# Resolve repo root (two levels up from this script) and load .env.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ROOT}/.env"
[ -f "${ENV_FILE}" ] || { echo "ERROR: ${ENV_FILE} not found (run: make env)"; exit 1; }
# shellcheck disable=SC1090
set -a; . "${ENV_FILE}"; set +a

COMPOSE="docker compose --env-file ${ENV_FILE} -f ${ROOT}/infra/compose/docker-compose.yml"
fail=0

check() { # name, command...
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf '  \033[32mOK\033[0m   %s\n' "${name}"
  else
    printf '  \033[31mFAIL\033[0m %s\n' "${name}"
    fail=1
  fi
}

echo "Health checks (ports from .env):"
# Postgres / Redis: exec the in-container probes via Compose.
check "postgres  pg_isready"               $COMPOSE exec -T postgres pg_isready -U "${POSTGRES__USER}" -d "${POSTGRES__DB}"
check "redis      PING"                      $COMPOSE exec -T redis redis-cli ping
# ClickHouse: HTTP /ping must return "Ok."
check "clickhouse GET /ping"                 bash -c "curl -fsS \"http://localhost:${CLICKHOUSE__PORT}/ping\" | grep -q Ok."
# MinIO: HTTP /minio/health/live must return 200.
check "minio      GET /minio/health/live"    curl -fsS "http://localhost:${MINIO__API_PORT}/minio/health/live"

if [ "${fail}" -ne 0 ]; then
  echo "One or more services are unhealthy."; exit 1
fi
echo "All four services healthy."
