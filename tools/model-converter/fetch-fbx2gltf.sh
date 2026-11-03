#!/usr/bin/env bash
# Operator step (TICKET-341): install the FBX2glTF fallback reader without root. Usage: fetch-fbx2gltf.sh [DEST]
# DEST defaults to ~/.local/share/simon-part-7/tools/FBX2glTF, where supervisor.py looks (or set SIMON7_FBX2GLTF).
# The binary comes from the npm package fbx2gltf@0.9.7-p1 and is pinned by sha256; a mismatch installs nothing.
set -euo pipefail
version=0.9.7-p1
sha=b38210352fdd29d50ba53a6514c3ff05ccbb5d1e0a6442db7a49834bf34a3145
dest="${1:-${SIMON7_FBX2GLTF:-$HOME/.local/share/simon-part-7/tools/FBX2glTF}}"
work="$(mktemp -d)"
cleanup() {
  rm -f "$work/pkg.tgz" "$work/package/bin/Linux/FBX2glTF"
  rmdir "$work/package/bin/Linux" "$work/package/bin" "$work/package" "$work" 2>/dev/null || true
}
trap cleanup EXIT
curl -fsSL -o "$work/pkg.tgz" "https://registry.npmjs.org/fbx2gltf/-/fbx2gltf-${version}.tgz"
tar -xzf "$work/pkg.tgz" -C "$work" package/bin/Linux/FBX2glTF
echo "${sha}  $work/package/bin/Linux/FBX2glTF" | sha256sum -c - >/dev/null
mkdir -p "$(dirname "$dest")"
install -m 0755 "$work/package/bin/Linux/FBX2glTF" "$dest"
echo "installed FBX2glTF ${version} at $dest"
