#!/bin/bash
# make hpc-outputs: inference for each fixture mode on HPC -> out/<mode>/ + stamp.json
# (same contract as k8s/gpu_outputs.sh; fingerprint taken before the run, see part2/check.py).
set -eo pipefail
HPC="${1:-<user>@<cluster-login-host>}"
ROOT=simon-part-2
cd "$(dirname "$0")/.."

for mode in single class; do
  [ -d "fixtures/input/$mode/frames" ] || { echo "skip $mode: no fixtures/input/$mode/frames"; continue; }
  fp=$(uv run --quiet python -m part2.check fingerprint "$mode")
  run_mode=$([ "$mode" = single ] && echo single || echo multi)
  echo "== $mode: syncing frames, sbatch --wait part2 run --mode $run_mode"
  ssh "$WAVE" "rm -rf $ROOT/data/fixture-$mode && mkdir -p $ROOT/data/fixture-$mode"
  rsync -a "fixtures/input/$mode/frames" "$HPC:$ROOT/data/fixture-$mode/"
  ssh "$WAVE" "cd $ROOT && sbatch --wait part2/hpc/run.sbatch $run_mode data/fixture-$mode/frames out/fixture-$mode"
  rm -rf "out/$mode" && mkdir -p "out/$mode"
  rsync -a --exclude frames "$HPC:$ROOT/out/fixture-$mode/" "out/$mode/"
  uv run --quiet python -m part2.check stamp "$mode" "$fp"
done
