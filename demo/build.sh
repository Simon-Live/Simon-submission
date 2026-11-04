#!/usr/bin/env bash
# demo/build.sh: rebuild demo/simon-end-to-end.mp4 and demo/captions.srt from sources, then run demo/check.py.
# Usage: demo/build.sh [--recapture] [--no-tts]
#   --recapture  restart a LOCAL server on a throwaway state dir and re-record the UI segments with Playwright
#                (do this after the result-screen or catalog UI changes land on the checkout you run it from).
#   --no-tts     reuse cached voice-over only (fails if a line changed).
# Env: DEMO_WORK (default /tmp/simon-demo-work), DEMO_PORT (17391), DEMO_MODULES_DIR (part submodules for the local
# server; default <repo>/modules, so run `make parts` first or point it at another checkout's modules).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
export DEMO_WORK="${DEMO_WORK:-/tmp/simon-demo-work}"
PORT="${DEMO_PORT:-17391}"
RECAPTURE=0; PYARGS=()
for a in "$@"; do
  case "$a" in
    --recapture) RECAPTURE=1 ;;
    --no-tts) PYARGS+=("--no-tts") ;;
    *) echo "unknown option $a" >&2; exit 64 ;;
  esac
done
if [ "$RECAPTURE" = 1 ] || [ ! -f "$DEMO_WORK/capture/marks.json" ]; then
  "$HERE/local-state.sh" stop || true
  "$HERE/local-state.sh" start
  trap '"$HERE/local-state.sh" stop' EXIT
  "$REPO/scripts/with-browser-slot.sh" node "$HERE/capture.mjs" "$DEMO_WORK/capture" "http://127.0.0.1:$PORT/"
fi
python3 "$HERE/build.py" --work "$DEMO_WORK" "${PYARGS[@]}"
python3 "$HERE/check.py" --work "$DEMO_WORK"
