#!/usr/bin/env bash
# Download NHANES 2011-2012 (_G) and 2013-2014 (_H) components into data/raw/nhanes,
# plus minute-level step counts (stepcount SSL algorithm) and wear predictions from
# PhysioNet. ~75 MB in total. Resumable; components missing in a cycle are skipped.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/data/raw/nhanes"
mkdir -p "$DEST"

# Demographics, diabetes, labs, exam, questionnaires, prescription medications.
COMPONENTS="DEMO DIQ GHB GLU INS BIOPRO TCHOL HDL TRIGLY ALB_CR BPX BMX BPQ MCQ KIQ_U SMQ RXQ_RX"
for cycle in "2011:G" "2013:H"; do
  year="${cycle%%:*}"; suffix="${cycle##*:}"
  for c in $COMPONENTS; do
    file="${c}_${suffix}.xpt"
    if [ -s "$DEST/$file" ]; then continue; fi
    url="https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/$year/DataFiles/$file"
    if curl -fsSL -C - -o "$DEST/$file.part" "$url"; then
      # CDC answers some missing files with an HTML page instead of a 404.
      if head -c 80 "$DEST/$file.part" | grep -qi "<html\|<!doctype"; then
        rm -f "$DEST/$file.part"; echo "skip $file (not in this cycle)"
      else
        mv "$DEST/$file.part" "$DEST/$file"; echo "ok   $file"
      fi
    else
      rm -f "$DEST/$file.part"; echo "skip $file (not available)"
    fi
  done
done

# Minute-level wrist steps (stepcount self-supervised model) and wear/sleep predictions.
PN="https://physionet.org/files/minute-level-step-count-nhanes/1.0.2/csv"
for f in nhanes_1440_scsslsteps.csv.xz nhanes_1440_PAXPREDM.csv.xz; do
  curl -fSL -C - -o "$DEST/$f" "$PN/$f" && echo "ok   $f"
done
echo "NHANES files in $DEST"
