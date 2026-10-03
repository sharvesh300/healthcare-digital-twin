#!/usr/bin/env bash
# Wipe this project's databases (twin + HAPI volume) and rebuild everything from
# the seeds. Downloaded data in data/ is kept. Asks for confirmation unless --yes.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" != "--yes" ]; then
  read -r -p "Delete the TimescaleDB/HAPI volume of this project and rebuild? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "aborted"; exit 1; }
fi
docker compose down -v
scripts/up.sh
scripts/pipeline.sh all
