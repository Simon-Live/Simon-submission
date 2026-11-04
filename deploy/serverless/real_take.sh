#!/usr/bin/env bash
# One real take on Modal before the site is public (docs/prod/serverless-real-take.md, serverless-compute.md AC-SC19).
#
#   deploy/serverless/real_take.sh --secrets-dir <folder> --clip <your own clip> --out <empty folder> [--runs N]
#
# It starts no server and opens no port: only this machine's Modal client runs, through the same p2_client.py route prod
# uses, on the token files in <folder>. The token never enters this script's environment or an argument. Spend is real:
# each run is one Modal `track` call and one `run` call, the first cold and the rest warm if they start within 60 s.
# Output: <out>/measurements.txt (one line a call, numbers only). Modal's copy goes when each call ends.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLIENT="$ROOT/deploy/serverless/p2_client.py"
usage() { echo "usage: real_take.sh --secrets-dir <folder> --clip <file> --out <empty folder> [--runs N]" >&2; exit 2; }

SECRETS="" CLIP="" OUT="" RUNS=2
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case "$1" in
    --secrets-dir) SECRETS="$2" ;;
    --clip) CLIP="$2" ;;
    --out) OUT="$2" ;;
    --runs) RUNS="$2" ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n "$SECRETS" && -n "$CLIP" && -n "$OUT" && "$RUNS" =~ ^[1-9]$ ]] || usage
[[ -f "$CLIP" ]] || { echo "the clip is not a file" >&2; exit 2; }
[[ ! -e "$OUT" || -z "$(ls -A "$OUT")" ]] || { echo "the output folder is not empty" >&2; exit 2; }
[[ "${FIRM_ENV:-}" != prod && -z "${SIMON7_STATE_DIR:-}" ]] || { echo "run this from a shell with no app settings, not from a stack" >&2; exit 2; }
SHA="$(git -C "$ROOT/modules/part-2" rev-parse HEAD)"
mkdir -p "$OUT/ledger"
FPS=10 TRACK_FPS=3  # part7/parts/p2_pose.py FPS and TRACK_FPS_SINGLE, the defaults a prod take uses (a test keeps them equal)
TIMER=()
if [[ -x /usr/bin/time ]]; then TIMER=(/usr/bin/time -f "client_peak_ram_kib %M"); fi

client() { # client <label> <client flags...>: one call, its whole output in <out>/<label>.log
  local label="$1" code=0
  shift
  "${TIMER[@]}" python3 -I "$CLIENT" --serverless --secrets-dir "$SECRETS" --ledger "$OUT/ledger" --job "real-take" \
    --status "$OUT/status-$label.json" --queue-wait 900 "$@" > "$OUT/$label.log" 2>&1 || code=$?
  { echo "$label exit=$code $(grep -h 'modal: measured' "$OUT/$label.log" | tail -n 1 || true)"
    grep -h 'client_peak_ram_kib' "$OUT/$label.log" | sed "s/^/$label /" || true; } >> "$OUT/measurements.txt"
  cat "$OUT/$label.log"
  [[ "$code" == 0 ]] || { echo "$label stopped with exit $code; see $OUT/$label.log" >&2; exit "$code"; }
}

client check --check-deploy --part2-sha "$SHA"
for ((i = 1; i <= RUNS; i++)); do
  client "track-$i" --sha "$SHA" -- track --input "$CLIP" --out "$OUT/run-$i/track" --fps "$TRACK_FPS" --tracker local-open
  client "pose-$i" --sha "$SHA" -- run --mode single --input "$CLIP" --out "$OUT/run-$i/part2" --fps "$FPS" --backend gpu
done
echo "measured: $OUT/measurements.txt"
