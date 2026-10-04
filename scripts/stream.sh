#!/usr/bin/env bash
# Stream simulated device readings into the live twin. Start the API first (scripts/replay.sh).
# Extra arguments are passed through, e.g. `scripts/stream.sh --from-now --speed 1`
# or `scripts/stream.sh --patient <uuid> --jitter 0.02 --drop-rate 0.01`.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run twin simulate-stream "$@"
