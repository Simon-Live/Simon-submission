#!/bin/bash
# make gpu-outputs: inference for each fixture mode on the GPU pod -> out/<mode>/ + stamp.json.
# Stamps use the fingerprint taken before the run (see part2/check.py).
set -eo pipefail
POD="${1:-user-part2-gpu}"
cd "$(dirname "$0")/.."

for mode in single class; do
  [ -d "fixtures/input/$mode/frames" ] || { echo "skip $mode: no fixtures/input/$mode/frames"; continue; }
  fp=$(uv run --quiet python -m part2.check fingerprint "$mode")
  run_mode=$([ "$mode" = single ] && echo single || echo multi)
  echo "== $mode: syncing frames, running part2 run --mode $run_mode"
  COPYFILE_DISABLE=1 tar -C "fixtures/input/$mode" -czf - frames | \
    kubectl exec -i "$POD" -- bash -c "rm -rf /workspace/fixtures/$mode && mkdir -p /workspace/fixtures/$mode && tar -xzf - -C /workspace/fixtures/$mode"
  kubectl exec "$POD" -- bash -c "cd /workspace/part2 && rm -rf /workspace/out/$mode && \
    python -m part2.cli run --mode $run_mode --input /workspace/fixtures/$mode/frames --out /workspace/out/$mode"
  rm -rf "out/$mode" && mkdir -p "out/$mode"
  kubectl exec "$POD" -- bash -c "cd /workspace/out/$mode && tar -czf - --exclude=frames ." | tar -xzf - -C "out/$mode"
  uv run --quiet python -m part2.check stamp "$mode" "$fp"
done
