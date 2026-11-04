#!/usr/bin/env bash
# Run the whole of Simon on this machine through the judges' relay (deploy/judges/README.md): Simon's Meta API key
# and Part 2 on Simon's Modal GPU, without a GPU, a key or a Modal account here. Open until Nov 9, 2026, 11:59 PM ET.
#   deploy/judges/run.sh            then open the address it prints (http://127.0.0.1:8727 unless that port is taken)
# Needs Python 3.12, uv, git, make and ffmpeg. SIMON_RELAY points it at another relay, SIMON_PORT picks the port.
set -euo pipefail

RELAY="${SIMON_RELAY:-https://shrutidoshi94--simon-judges-relay-web.us-east.modal.run}"
RELAY="${RELAY%/}"
cd "$(dirname "$0")/../.."

echo "Simon judges' relay: $RELAY"
if ! health="$(curl -fsS --max-time 30 "$RELAY/health")"; then
  echo "The relay did not answer. Try again in a minute; if it stays down, use https://simon.live instead." >&2
  exit 1
fi
echo "  $health"
case "$health" in *'"open":false'*)
  echo "The relay is closed (judging ended, or the budget is spent). https://simon.live still works." >&2
  exit 1 ;;
esac

# The parts need a key value to start; the relay drops it and uses its own. A real key already here is left alone.
KEYS="${SIMON7_KEYS_DIR:-$HOME/.config/simon/keys}"
mkdir -p "$KEYS"
[ -s "$KEYS/MODEL_API_KEY" ] || printf 'judges-relay\n' > "$KEYS/MODEL_API_KEY"
grep -qs '^MODEL_API_KEY=' modules/part-1/.env || printf 'MODEL_API_KEY=judges-relay\n' >> modules/part-1/.env

export SIMON7_KEYS_DIR="$KEYS"
export PART5_META_KEY_FILE="$KEYS/MODEL_API_KEY"   # Part 5's second opinion reads its key from this file
export SIMON_META_API="$RELAY/meta/v1"             # Part 1, Part 5 and Part 7's Meta API calls go to the relay
export SIMON_PART2_RELAY="$RELAY"                  # Part 2 runs on the relay's Modal GPU
export SIMON7_PART2_REMOTE=modal
export SIMON7_P2_TRACKER=local-sam31               # tracking on that GPU (the relay insists on it anyway)
export SIMON7_PART1_SPEND_CAP_USD="${SIMON7_PART1_SPEND_CAP_USD:-5}"   # Part 1 runs only with a cap set

# the first free port from SIMON_PORT (default 8727): another Simon or app already on 8727 must not stop this one
PORT="${SIMON_PORT:-8727}"
port_free() { python3 -c "import socket,sys; s=socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1])))" "$1" 2>/dev/null; }
for _ in $(seq 1 20); do port_free "$PORT" && break; echo "Port $PORT is in use; trying $((PORT + 1))."; PORT=$((PORT + 1)); done

make setup
make setup-parts || echo "Part setup reported a problem above; Part 2 runs on the relay, so the app may still work." >&2
echo
echo "Starting Simon: open http://127.0.0.1:$PORT"
exec uv run python -m part7 serve --host 127.0.0.1 --port "$PORT" --base-path /
