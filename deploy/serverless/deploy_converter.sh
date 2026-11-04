#!/usr/bin/env bash
# Deploy the model converter to the operator's Modal workspace (docs/specs/model-convert.md "On Modal"). It is an app of its
# own, on a CPU, so this moves nothing a take uses and needs no Part 2 checkout. The token comes from the caller's Modal
# profile or environment, or with `--secrets-dir <folder>` from the two 0600 token files there, never into an argument or a log.
set -euo pipefail
if [[ "${1:-}" == --secrets-dir ]]; then
  [[ -n "${2:-}" ]] || { echo "usage: deploy_converter.sh [--secrets-dir <folder>]" >&2; exit 2; }
  for name in MODAL_TOKEN_ID MODAL_TOKEN_SECRET; do
    [[ -s "$2/$name" ]] || { echo "$name is missing or empty in that folder" >&2; exit 2; }
    export "$name=$(< "$2/$name")"
  done
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
uv run --no-project --with-requirements deploy/serverless/modal-requirements.txt modal deploy deploy/serverless/convert_app.py
# Only after a deploy that worked: the server and prod/up.sh refuse a converter whose stamp is not this source's.
uv run --no-project --with-requirements deploy/serverless/modal-requirements.txt python -I deploy/serverless/p2_client.py --stamp-deploy --converter
