#!/usr/bin/env bash
# Operator step: build the converter image. Usage: build.sh [4.5|3.6]   (default 4.5)
# The tag is simon7-model-converter:blender-<series>. Needs network once, for the pinned Blender tarball.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
series="${1:-4.5}"
case "$series" in
  4.5) version=4.5.15; sha=0d2b8bb2efe97e6c8eb57de6b7322f8800e1984e3125b60decca5f6771e4773e ;;
  3.6) version=3.6.23; sha="${BLENDER_36_SHA256:-}" ;;
  *) echo "build.sh: series must be 4.5 or 3.6" >&2; exit 2 ;;
esac
if [[ -z "$sha" ]]; then
  sha="$(curl -fsSL "https://download.blender.org/release/Blender${series}/blender-${version}.sha256" \
    | awk -v f="blender-${version}-linux-x64.tar.xz" '$2==f {print $1}')"
fi
[[ -n "$sha" ]] || { echo "build.sh: no sha256 for Blender ${version}" >&2; exit 1; }
exec docker build -t "simon7-model-converter:blender-${series}" \
  --build-arg "BLENDER_SERIES=${series}" --build-arg "BLENDER_VERSION=${version}" --build-arg "BLENDER_SHA256=${sha}" \
  "$HERE"
