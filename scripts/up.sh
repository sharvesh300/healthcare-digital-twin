#!/usr/bin/env bash
# Start the infrastructure (TimescaleDB + HAPI FHIR) and wait until both answer.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
set -a; source .env; set +a

docker compose up -d
printf "waiting for TimescaleDB"
until docker compose exec -T db pg_isready -U "${POSTGRES_USER:-twin}" -d "${POSTGRES_DB:-twin}" >/dev/null 2>&1; do
  printf "."; sleep 2
done
printf " ok\nwaiting for HAPI FHIR"
until curl -sf -o /dev/null "http://localhost:${FHIR_PORT:-8080}/fhir/metadata"; do
  printf "."; sleep 3
done
echo " ok"
echo "TimescaleDB: localhost:${PG_PORT:-5432}   HAPI FHIR: http://localhost:${FHIR_PORT:-8080}/fhir"
