#!/usr/bin/env bash
# Serve the Simon app on 127.0.0.1 with Part 6 as a child process (docs/dev/DEVELOPING.md).
# Port: SIMON7_PORT (default 8727). Phrasing: SIMON7_PHRASING=template|live (default live).
# Extra arguments go to `python -m part7 serve` (for example --state <dir>).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
exec uv run python -m part7 serve --host 127.0.0.1 --port "${SIMON7_PORT:-8727}" --base-path / "$@"
