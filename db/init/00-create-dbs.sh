#!/usr/bin/env bash
# Runs once on first container start. POSTGRES_DB (=twin) already exists and gets
# its schema from `uv run twin init-db` (SQLAlchemy models). Here we only add the
# separate database that HAPI FHIR owns and manages itself.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  CREATE DATABASE ${HAPI_DB:-hapi};
SQL
