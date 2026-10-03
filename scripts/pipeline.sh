#!/usr/bin/env bash
# Run the twin pipeline on the host. No arguments = every step (`twin all`);
# otherwise the arguments are passed through, e.g. `scripts/pipeline.sh reconcile`.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f data/raw/cgmacros/bio.csv ]; then
  echo "CGMacros data missing: run seeds/download_cgmacros.sh" >&2; exit 1
fi
if [ ! -d data/synthea/fhir ]; then
  echo "Synthea cohort missing: run seeds/generate_cohort.sh" >&2; exit 1
fi
if [ $# -eq 0 ]; then set -- all; fi
exec uv run twin "$@"
