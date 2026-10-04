#!/usr/bin/env bash
# Generate a Synthea cohort (runs on the host; needs Java 17).
#   default            diabetic cohort for CGMacros twins -> data/synthea/
#   COHORT_DIR=synthea_general KEEP_MODULE=none AGES=35-65 POPULATION=200 SEED=43
#                      general population for BIG IDEAs twins -> data/synthea_general/
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
AGES="${AGES:-25-75}"
# Default: diabetic cohort for CGMacros. KEEP_MODULE=none -> general population.
KEEP_MODULE="${KEEP_MODULE:-src/main/resources/keep_modules/keep_diabetes.json}"
OUT="$ROOT/data/${COHORT_DIR:-synthea}"

rm -rf "$OUT/fhir" "$OUT/metadata" "$OUT/cohort_index.json"
mkdir -p "$OUT"
cd "$SYNTHEA_DIR"
KEEP_ARGS=()
if [ "$KEEP_MODULE" != "none" ]; then KEEP_ARGS=(-k "$KEEP_MODULE"); fi
./run_synthea -s "$SEED" -cs "$SEED" -r "$REFERENCE_DATE" -p "$POPULATION" -a "$AGES" ${KEEP_ARGS[@]+"${KEEP_ARGS[@]}"} \
  --generate.thread_pool_size=1 \
  --exporter.baseDirectory="$OUT/" \
  --exporter.fhir.export=true \
  --exporter.hospital.fhir.export=true \
  --exporter.practitioner.fhir.export=true \
  --exporter.csv.export=false
echo "Synthea bundles in $OUT/fhir"
