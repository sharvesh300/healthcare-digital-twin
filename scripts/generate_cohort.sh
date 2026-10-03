#!/usr/bin/env bash
# Generate a diabetic Synthea cohort into data/synthea/ (runs on the host; needs Java 17).
#
# Reproducible: the same SEED + REFERENCE_DATE + POPULATION gives the same patients.
# Synthea otherwise anchors histories to the current clock time and generates in
# parallel, so each run produces different people -- which re-matches participants.
# If you do change the cohort, `twin all` re-matches and prunes the old FHIR patients.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYNTHEA_DIR="${SYNTHEA_DIR:-$HOME/testing/synthea}"
POPULATION="${POPULATION:-150}"
SEED="${SEED:-42}"
REFERENCE_DATE="${REFERENCE_DATE:-20261003}"   # YYYYMMDD: "today" in the EHR timeline
OUT="$ROOT/data/synthea"

rm -rf "$OUT/fhir" "$OUT/metadata" "$OUT/cohort_index.json"
mkdir -p "$OUT"
cd "$SYNTHEA_DIR"
./run_synthea -s "$SEED" -cs "$SEED" -r "$REFERENCE_DATE" -p "$POPULATION" -a 25-75 \
  -k src/main/resources/keep_modules/keep_diabetes.json \
  --generate.thread_pool_size=1 \
  --exporter.baseDirectory="$OUT/" \
  --exporter.fhir.export=true \
  --exporter.hospital.fhir.export=true \
  --exporter.practitioner.fhir.export=true \
  --exporter.csv.export=false
echo "Synthea bundles in $OUT/fhir"
