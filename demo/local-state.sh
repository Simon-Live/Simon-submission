#!/usr/bin/env bash
# demo/local-state.sh: build a throwaway Part 7 state dir for the video capture and start a LOCAL server on it.
# Usage: demo/local-state.sh start|stop   (env: DEMO_WORK, default /tmp/simon-demo-work; DEMO_PORT, default 17391)
# Reads the finished job 5277380db1e1 and a few catalog entries READ ONLY from the staging state dir and copies
# them (DEMO_LIVE=1 adds the Meta key and a private Part 1 copy for the fresh jobs). It never touches staging, never writes there, never uses the staging port.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
WORK="${DEMO_WORK:-/tmp/simon-demo-work}"
PORT="${DEMO_PORT:-17391}"
SRC="${DEMO_SOURCE_STATE:-$HOME/.local/state/simon-part-7/staging}"
STATE="$WORK/state"
JOBS="${DEMO_JOBS:-5277380db1e1 cc7cd5469055 0ec688188727 50462291497b 2b7b67273406 a62b8df23e3a 3a6341ce3299}"
ENTRIES="${DEMO_ENTRIES:-body-squat-19b06562 arm-wave jumping-jack forward-lunge hip-twist side-step squat shruti-floss-c7b8db83 dance-expressions-6b2729e1}"

case "${1:-}" in
  start)
    mkdir -p "$WORK" "$STATE/jobs" "$STATE/catalog"
    for j in $JOBS; do [ -d "$SRC/jobs/$j" ] && { [ -d "$STATE/jobs/$j" ] || cp -r "$SRC/jobs/$j" "$STATE/jobs/$j"; }; done
    for e in $ENTRIES; do [ -d "$SRC/catalog/$e" ] && { [ -d "$STATE/catalog/$e" ] || cp -r "$SRC/catalog/$e" "$STATE/catalog/$e"; }; done
    export SIMON7_P2_TRACK_WORKER=0   # no warm GPU worker: the demo server must not hold the shared card between jobs
    cd "${DEMO_SERVER_REPO:-$REPO}"   # the tree whose web/ and part7/ the server runs (default: this checkout)
    export SIMON7_MODULES_DIR="${DEMO_MODULES_DIR:-$REPO/modules}"
    if [ "${DEMO_LIVE:-0}" = 1 ]; then
      # Live Meta calls for the fresh jobs: the key reaches this server process only (never printed), and Part 1 runs
      # from a private copy of its module so its inbox, temporary .env and spend ledger never touch another checkout.
      export SIMON7_KEYS_DIR="${DEMO_KEYS_DIR:-$HOME/.config/firm/operator-keys}"
      PRIV="$WORK/modules"; mkdir -p "$PRIV"
      for p in 2 3 4 5 6; do [ -e "$PRIV/part-$p" ] || ln -s "$SIMON7_MODULES_DIR/part-$p" "$PRIV/part-$p"; done
      [ -e "$PRIV/part-1" ] || cp -a "$SIMON7_MODULES_DIR/part-1" "$PRIV/part-1"
      export SIMON7_MODULES_DIR="$PRIV"
    fi
    setsid nohup python3 -m part7 serve --host 127.0.0.1 --port "$PORT" --base-path / --state "$STATE" \
      > "$WORK/serve.log" 2>&1 < /dev/null &
    echo $! > "$WORK/serve.pid"
    for _ in $(seq 1 30); do curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && { echo "up on $PORT"; exit 0; }; sleep 1; done
    echo "server did not start; see $WORK/serve.log" >&2; exit 1 ;;
  stop)
    if [ -f "$WORK/serve.pid" ]; then kill "$(cat "$WORK/serve.pid")" 2>/dev/null || true; rm -f "$WORK/serve.pid"; fi ;;
  *) echo "usage: $0 start|stop" >&2; exit 64 ;;
esac
