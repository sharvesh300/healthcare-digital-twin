#!/usr/bin/env bash
# Serve the live sensor feed (default http://127.0.0.1:8765, ws://.../ws/patients/{id}).
# Extra arguments are passed through, e.g. `scripts/replay.sh --host 0.0.0.0 --port 9000`.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run twin replay "$@"
