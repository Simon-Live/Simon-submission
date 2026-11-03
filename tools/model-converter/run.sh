#!/bin/sh
# Container entry (ADR-0017). Usage: run.sh blender <blender args> -- <input> <output.glb>
# The jail has no writable mount: Blender writes <output.glb> on the container's tmpfs and the GLB leaves through
# stdout. Blender's own output goes to stderr so stdout carries only the GLB bytes.
# TICKET-341: convert.py writes its outcome to result.json beside the output. Once the command has exited, nothing
# from the upload can print any more, so the file is emitted here as the last stderr line, prefixed with the tag the
# supervisor passed in SIMON7_RESULT_TAG (a fresh random value per run): a forged line in the log never has it.
set -u
for last; do :; done
outdir="$(dirname "$last")"
mkdir -p "$outdir"
tag="${SIMON7_RESULT_TAG:-}"
env -u SIMON7_RESULT_TAG timeout -s KILL "${CONVERT_TIMEOUT_S:-170}" "$@" >&2  # the converter never sees the tag
code=$?
if [ -n "$tag" ] && [ -s "$outdir/result.json" ]; then
  printf '\n%s %s\n' "$tag" "$(tr -d '\n\r' < "$outdir/result.json" | head -c 65536)" >&2
fi
[ "$code" -eq 0 ] || exit "$code"
[ -s "$last" ] || { echo "convert: no output" >&2; exit 3; }
cat "$last"
