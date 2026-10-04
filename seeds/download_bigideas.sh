#!/usr/bin/env bash
# BIG IDEAs Glycemic Variability and Wearable Device Data (PhysioNet, ODC-By, open access):
# 16 adults (35-65, elevated glucose / prediabetes) with Dexcom G6 CGM and an Empatica E4
# wristband. Downloads CGM, heart rate, inter-beat intervals (HRV), skin temperature and
# EDA (~3 GB); skips raw accelerometer/BVP (~2.3 GB per person) and food logs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/data/raw/bigideas"
# PhysioNet's open-data S3 mirror (physionet.org itself throttles to ~10 KB/s here).
BASE="https://physionet-open.s3.amazonaws.com/big-ideas-glycemic-wearable/1.1.2"
mkdir -p "$DEST"
curl -fsSL -o "$DEST/Demographics.csv" "$BASE/Demographics.csv"
# Download, then verify every file's size against the server and retry mismatches
# (connection resets leave truncated files that curl -C - resumes).
for attempt in 1 2 3 4 5; do
  bad=0
  for i in $(seq 1 16); do
    id=$(printf "%03d" "$i")
    mkdir -p "$DEST/$id"
    for kind in Dexcom HR IBI TEMP EDA; do
      file="${kind}_${id}.csv"
      want=$(curl -sfI "$BASE/$id/$file" | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}')
      have=$(stat -f %z "$DEST/$id/$file" 2>/dev/null || stat -c %s "$DEST/$id/$file" 2>/dev/null || echo 0)
      if [ -n "$want" ] && [ "$have" != "$want" ]; then
        bad=1
        curl -fsSL -C - -o "$DEST/$id/$file" "$BASE/$id/$file" && echo "ok $id/$file" || echo "retry $id/$file"
      fi
    done
  done
  [ "$bad" = 0 ] && break
done
[ "$bad" = 0 ] && echo "all files verified against server sizes" || { echo "some files still incomplete"; exit 1; }
echo "BIG IDEAs files in $DEST"
