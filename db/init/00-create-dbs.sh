#!/usr/bin/env bash
# Runs once on first container start. POSTGRES_DB (=twin) already exists; the
# *.sql files that follow are applied to it by the entrypoint. Here we add the
# separate database that HAPI FHIR owns.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  CREATE DATABASE ${HAPI_DB:-hapi};
SQL
