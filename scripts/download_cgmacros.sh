#!/usr/bin/env bash
# Fetch the CGMacros CSVs (PhysioNet, open access) into data/raw/cgmacros.
# Only the CSV members are pulled from the remote zip via HTTP range requests;
# the full 657 MB archive (mostly meal photos) is not downloaded.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$ROOT/scripts/fetch_cgmacros.py" "$ROOT/data/raw/cgmacros"
