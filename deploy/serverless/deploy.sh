#!/usr/bin/env bash
# Deploy Simon's GPU app to the operator's Modal workspace and stamp its version (docs/specs/serverless-compute.md AC-SC16,
# docs/prod/serverless-real-take.md). Run from a full checkout of the release being deployed, with `make parts` done:
# Part 2's repo is private, so the image is built from modules/part-2. Modal's token comes from the caller's own Modal
# profile or environment, or with `--secrets-dir <folder>` from the two 0600 token files there, into this script's own
# environment and never into an argument or a log.
# Limits come from prod/compute.conf, so Modal's max_containers equals Part 7's job workers.
# It deploys all three apps; `--image3d-only` deploys the picture app alone and leaves the others as they are (AC-SC20).
set -euo pipefail
ONLY_IMAGE3D=""
if [[ "${1:-}" == --image3d-only ]]; then ONLY_IMAGE3D=1; shift; fi
if [[ "${1:-}" == --secrets-dir ]]; then
  [[ -n "${2:-}" ]] || { echo "usage: deploy.sh [--secrets-dir <folder>]" >&2; exit 2; }
  for name in MODAL_TOKEN_ID MODAL_TOKEN_SECRET; do
    [[ -s "$2/$name" ]] || { echo "$name is missing or empty in that folder" >&2; exit 2; }
    export "$name=$(< "$2/$name")"
  done
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REQ="$ROOT/deploy/serverless/modal-requirements.txt"
PART2="$(git -C "$ROOT/modules/part-2" rev-parse HEAD)"
MAX="$(sed -n 's/^SIMON7_SERVERLESS_MAX_CONCURRENT=\([0-9][0-9]*\)[[:space:]]*$/\1/p' "$ROOT/prod/compute.conf" | tail -n 1)"
[[ -n "$MAX" ]] || { echo "prod/compute.conf sets no SIMON7_SERVERLESS_MAX_CONCURRENT" >&2; exit 2; }

cd "$ROOT"
# Only after a deploy that worked: prod/up.sh refuses a release until these stamps match it.
if [[ -z "$ONLY_IMAGE3D" ]]; then
  SIMON7_SERVERLESS_MAX_CONCURRENT="$MAX" uv run --no-project --with-requirements "$REQ" \
    modal deploy deploy/serverless/part2_app.py
  uv run --no-project --with-requirements "$REQ" python -I deploy/serverless/p2_client.py --stamp-deploy --part2-sha "$PART2"
fi
SIMON7_SERVERLESS_MAX_CONCURRENT="$MAX" uv run --no-project --with-requirements "$REQ" \
  modal deploy deploy/serverless/image3d_app.py
uv run --no-project --with-requirements "$REQ" python -I deploy/serverless/p2_client.py --stamp-deploy --image3d --part2-sha "$PART2"
if [[ -z "$ONLY_IMAGE3D" ]]; then
  bash "$ROOT/deploy/serverless/deploy_converter.sh"
fi
