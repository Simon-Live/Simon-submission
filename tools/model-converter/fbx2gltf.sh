#!/bin/sh
# Fallback FBX reader (TICKET-341, docs/specs/model-convert.md). Runs in the same jail as Blender, by run.sh:
#   sh /opt/simon/fbx2gltf.sh /in/input.fbx /tmp/out/model.glb
# FBX2glTF (the Autodesk FBX SDK) reads the FBX files Blender cannot (text FBX, FBX 6.1 and older), then convert.py
# gives its GLB the same clean-up a Blender import gets: deform bones only, one merged mesh when unrigged, metres.
set -eu
src="$1"
out="$2"
mkdir -p /tmp/raw /tmp/fbxsdk
cd /tmp
/opt/fbx2gltf/FBX2glTF -b --pbr-metallic-roughness --fbx-temp-dir /tmp/fbxsdk -i "$src" -o /tmp/raw/model >&2
[ -s /tmp/raw/model.glb ] || { echo "convert: FBX2glTF wrote no GLB" >&2; exit 3; }
exec blender -b --factory-startup -Y --python-exit-code 1 --python /opt/simon/convert.py -- /tmp/raw/model.glb "$out" fbx2gltf
