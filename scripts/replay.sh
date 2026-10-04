#!/usr/bin/env bash
# Serve the twin API: /patients, /twin/{id}, simulations, and the WebSocket replay
# Extra arguments are passed through, e.g. `scripts/replay.sh --host 0.0.0.0 --port 9000`.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run twin serve "$@"
