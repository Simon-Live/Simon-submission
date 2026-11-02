"""Redo the limb split of a GLB that `part2 autorig` or `part2 image3d` already wrote, without the GPU.

    glb, report = reskin(glb_bytes)          # report: {"changed", "bridging_triangles_cut", "stretch": {...}}
    part2 reskin IN.glb OUT.glb              # the same from the shell; prints the report as JSON

A model rigged before TICKET-058 carries weights that ramp across a hand fused to a thigh, so its hands stay glued to
the thighs when it moves. The original nearest-body weights are not kept, so `reskin` runs `autorig_weights.refine` on
the weights the file has (the split keeps a vertex's own limb and the torso, so weights that were right stay close to
what they were) and `cut_bridges` on its triangles. Only JOINTS_0, WEIGHTS_0 and the triangle indices change: vertices,
UVs, normals, texture, skeleton and every other byte of the binary chunk stay where they were. numpy only.
Spec: docs/specs/autorig.md (AC-24).
"""
import json
import sys
from pathlib import Path

import numpy as np

from part2 import autorig_glb, autorig_pose, autorig_weights

GENERATOR = "simon-part-2 autorig"


class ReskinError(ValueError):
    """The file is not a GLB that part2 autorig wrote."""


def _write(blob: bytearray, doc: dict, accessor: int, arr: np.ndarray) -> None:
    """Overwrite an accessor's values in place (same view, same type); its count becomes len(arr)."""
    acc = doc["accessors"][accessor]
    view = doc["bufferViews"][acc["bufferView"]]
    data = np.ascontiguousarray(arr).tobytes()
    if view.get("byteStride") or len(data) > view["byteLength"] - acc.get("byteOffset", 0):
        raise ReskinError("an accessor does not have room for its new values")
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    blob[start:start + len(data)] = data
    acc["count"] = len(arr)


def reskin(glb: bytes) -> tuple[bytes, dict]:
    """(new GLB bytes, report). Raises ReskinError on a file part2 autorig did not write."""
    try:
        rig = autorig_pose.read_rig(glb)
    except (autorig_glb.GlbError, KeyError, IndexError, TypeError, ValueError) as e:
        raise ReskinError(f"not a GLB part2 autorig wrote: {e}") from e
    doc = rig["doc"]
    if not str(doc.get("asset", {}).get("generator", "")).startswith(GENERATOR):
        raise ReskinError("not a GLB part2 autorig wrote")
    v, f, joints, parents, mapping = rig["vertices"], rig["faces"], rig["joints"], rig["parents"], rig["mapping"]
    prim = doc["meshes"][0]["primitives"][0]
    at = prim["attributes"]
    if doc["accessors"][at["JOINTS_0"]]["componentType"] != 5123 or doc["accessors"][prim["indices"]]["componentType"] != 5125:
        raise ReskinError("the skin or the triangles are not stored as part2 autorig stores them")
    idx, w = autorig_weights.refine(v, f, joints, parents, mapping, rig["idx"], rig["w"])
    shards: dict = {}
    faces, cut = autorig_weights.cut_bridges(v, f, joints, parents, mapping, idx, w, shards)
    stretch = {"before": autorig_pose.pose_stretch(v, f, joints, parents, rig["idx"], rig["w"], mapping),
               "after": autorig_pose.pose_stretch(v, faces, joints, parents, idx, w, mapping)}
    blob = bytearray(_binary(glb))
    _write(blob, doc, at["JOINTS_0"], idx.astype("<u2"))
    _write(blob, doc, at["WEIGHTS_0"], w.astype("<f4"))
    _write(blob, doc, prim["indices"], faces.astype("<u4").reshape(-1))
    changed = cut > 0 or not (np.array_equal(idx, rig["idx"]) and np.allclose(w, rig["w"], atol=1e-6))
    report = {"changed": bool(changed), "bridging_triangles_cut": cut, "triangles": len(faces), **shards,
              "stretch": {k: {pose: {m: round(x, 2) if isinstance(x, float) else x for m, x in d.items()}
                              for pose, d in per.items()} for k, per in stretch.items()}}
    return autorig_glb._pack(doc, bytes(blob)), report


def _binary(glb: bytes) -> bytes:
    pos = 12
    while pos < len(glb):
        length, kind = np.frombuffer(glb, dtype="<u4", count=1, offset=pos)[0], glb[pos + 4:pos + 8]
        if kind == b"BIN\x00":
            return glb[pos + 8:pos + 8 + int(length)]
        pos += 8 + int(length)
    raise ReskinError("the GLB has no binary chunk")


def command(src, out) -> int:
    """`part2 reskin IN OUT`: 0 with the report on stdout, 2 when IN is not an autorig GLB. OUT is written whole."""
    try:
        data, report = reskin(Path(src).read_bytes())
    except (OSError, ReskinError) as e:
        print(f"part2: {e}", file=sys.stderr)
        return 2
    part = Path(str(out) + ".part")
    part.write_bytes(data)
    part.replace(out)
    print(json.dumps(report, sort_keys=True))
    return 0
