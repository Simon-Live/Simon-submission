"""avatar GLB export (part2.mhr_export), docs/specs/avatar.md AC-5 to AC-9, AC-12, AC-17, AC-18; synthetic rig, no GPU."""
import ast
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from avatar_rig import body, joints_and_parents

from part2 import avatar
from part2 import mhr_export as mx


@pytest.fixture(scope="module")
def built():
    static, v, j = body()
    res = mx.build_glb(static, v, j)
    doc, blob = mx.read_glb(res.glb)
    return static, v, j, res, doc, blob


def _world(doc):
    """World positions of the nodes, summing local translations down the tree (rotations are identity by AC-7)."""
    nodes, pos = doc["nodes"], {}

    def walk(i, base):
        pos[i] = base + np.array(nodes[i].get("translation", [0, 0, 0]))
        for c in nodes[i].get("children", []):
            walk(c, pos[i])

    for r in doc["scenes"][0]["nodes"]:
        walk(r, np.zeros(3))
    return pos


def test_ac5_structure(built):
    _, v, _, _res, doc, blob = built
    assert doc["asset"]["version"] == "2.0" and len(doc["scenes"]) == 1 and len(doc["meshes"]) == 1
    prim = doc["meshes"][0]["primitives"][0]
    assert set(prim["attributes"]) == {"POSITION", "NORMAL", "JOINTS_0", "WEIGHTS_0"} and "indices" in prim
    assert len(doc["skins"]) == 1 and len(doc["skins"][0]["joints"]) == 127
    assert "textures" not in doc and "images" not in doc and "uri" not in json.dumps(doc)
    assert all("uri" not in b for b in doc["buffers"]) and doc["buffers"][0]["byteLength"] == len(blob)
    assert mx.read_accessor(doc, blob, prim["attributes"]["POSITION"]).shape == (len(v), 3)
    assert mx.read_accessor(doc, blob, doc["skins"][0]["inverseBindMatrices"]).shape == (127, 16)
    normals = mx.read_accessor(doc, blob, prim["attributes"]["NORMAL"])
    assert np.allclose(np.linalg.norm(normals, axis=1)[np.linalg.norm(normals, axis=1) > 0], 1, atol=1e-4)


def test_ac6_influences(built):
    _, _, _, _, doc, blob = built
    a = doc["meshes"][0]["primitives"][0]["attributes"]
    w, ji = mx.read_accessor(doc, blob, a["WEIGHTS_0"]), mx.read_accessor(doc, blob, a["JOINTS_0"])
    assert w.shape[1] == 4 and (w >= 0).all() and np.allclose(w.sum(1), 1, atol=1e-5)
    assert ji.max() < 127


def test_ac7_bind_is_identity(built):
    _, v, j, _res, doc, blob = built
    a = doc["meshes"][0]["primitives"][0]["attributes"]
    pos, ji, w = (mx.read_accessor(doc, blob, a[k]) for k in ("POSITION", "JOINTS_0", "WEIGHTS_0"))
    ibm = mx.read_accessor(doc, blob, doc["skins"][0]["inverseBindMatrices"]).reshape(127, 4, 4)
    world = _world(doc)
    for i in range(127):
        node = doc["nodes"][i]
        assert "rotation" not in node and "scale" not in node and "matrix" not in node
        m = np.eye(4)
        m[:3, 3] = world[i]
        assert np.abs((m @ ibm[i].T) - np.eye(4)).max() < 1e-6  # joint world times inverse bind is identity
    skinned = np.zeros_like(pos, dtype=np.float64)
    for k in range(4):
        for vi in range(len(pos)):
            m = np.eye(4)
            m[:3, 3] = world[int(ji[vi, k])]
            skinned[vi] += w[vi, k] * (m @ ibm[int(ji[vi, k])].T @ np.append(pos[vi], 1))[:3]
    assert np.abs(skinned - pos).max() < 1e-6
    drop = -v[:, 1].min()
    assert np.allclose(world[1], j[1] + [0, drop, 0], atol=1e-6)  # a node's world position is the MHR joint position


def test_ac8_frame_and_ground(built):
    _, _, _, res, doc, blob = built
    pos = mx.read_accessor(doc, blob, doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"])
    assert pos[:, 1].min() == 0 and res.height_m == round(float(pos[:, 1].max()), 3)
    world = _world(doc)
    n = res.mapped
    assert world[n["leftUpperArm"]][0] > 0 > world[n["rightUpperArm"]][0]
    assert world[n["leftToes"]][2] > world[n["leftFoot"]][2] - 0.2 and world[n["head"]][1] > world[n["hips"]][1]


def test_ac9_canonical_names_and_chains(built):
    _, _, _, res, doc, _ = built
    assert len(res.mapped) == 22
    for bone, idx in res.mapped.items():
        assert doc["nodes"][idx]["name"] == bone
    assert sum(1 for n in doc["nodes"][:127] if n["name"].startswith("mhr_")) == 127 - 22
    parent = {c: i for i, n in enumerate(doc["nodes"]) for c in n.get("children", [])}

    def under(a, b):
        while a in parent:
            a = parent[a]
            if a == b:
                return True
        return False

    m = res.mapped
    for side in ("left", "right"):
        assert under(m[side + "Foot"], m[side + "LowerLeg"]) and under(m[side + "LowerLeg"], m[side + "UpperLeg"])
        assert under(m[side + "Hand"], m[side + "LowerArm"]) and under(m[side + "LowerArm"], m[side + "UpperArm"])
        assert under(m[side + "UpperLeg"], m["hips"])
    assert under(m["head"], m["neck"])


def test_licence_is_in_the_glb(built):
    _, _, _, _, doc, _ = built
    assert doc["asset"]["extras"]["licence"] == "SAM License; MHR Apache-2.0 notice"
    assert "Apache-2.0" in doc["asset"]["copyright"] and "SAM License" in doc["asset"]["copyright"]


def test_ac12_deterministic():
    a, b = body(), body()
    assert mx.build_glb(*a).glb == mx.build_glb(*b).glb


def test_weight_error_is_recorded_not_rejected(built):
    static, *_ = built[:1]
    assert static.max_weight_error > 0.01  # the fixture has sums 2 percent off; the export still succeeded
    assert built[3].max_weight_error == static.max_weight_error


def test_top_four_influences_renormalised():
    s = mx.skin_arrays(np.zeros((0, 3), int), np.array([-1]), np.array([0] * 6), np.array([5, 4, 3, 2, 1, 0]),
                       np.array([.3, .25, .2, .15, .06, .04]), 1)
    assert list(s.skin_idx[0]) == [5, 4, 3, 2] and abs(s.skin_w[0].sum() - 1) < 1e-12


def test_vertex_with_fewer_than_four_is_padded_with_zero_weight():
    s = mx.skin_arrays(np.zeros((0, 3), int), np.array([-1]), np.array([0, 0]), np.array([7, 9]), np.array([.5, .5]), 1)
    assert list(s.skin_idx[0]) == [7, 9, 0, 0] and list(s.skin_w[0]) == [.5, .5, 0, 0]


def test_vertex_without_weight_is_refused():
    with pytest.raises(mx.ExportError, match="no positive weight"):
        mx.skin_arrays(np.zeros((0, 3), int), np.array([-1]), np.array([0]), np.array([1]), np.array([0.0]), 2)


@pytest.mark.parametrize("edit,check", [
    ("short", "126 joints"),
    ("swap_sides", "left"),
    ("upside_down", "stacked upward"),
    ("reparent", "is not under"),
])
def test_ac17_layout_is_checked(edit, check):
    parents, joints = joints_and_parents()
    if edit == "short":
        parents, joints = parents[:126], joints[:126]
    elif edit == "swap_sides":
        joints[:, 0] *= -1
    elif edit == "upside_down":
        joints[:, 1] *= -1
    else:
        parents[4] = 1  # the left foot no longer under the lower leg
    with pytest.raises(mx.LayoutError, match=check) as e:
        mx.canonical_map(parents, joints)
    assert str(e.value).startswith("the MHR model does not have the joint layout avatar expects")


def test_ac17_nothing_is_built_for_a_wrong_layout():
    static, v, j = body()
    static.parents[4] = 1
    with pytest.raises(mx.LayoutError):
        mx.build_glb(static, v, j)


@pytest.mark.parametrize("what", ["nan", "tiny", "giant"])
def test_ac18_implausible_body(what):
    static, v, j = body()
    if what == "nan":
        v[3, 0] = np.nan
    else:
        s = 0.1 if what == "tiny" else 3.0
        v, j = v * s, j * s
    with pytest.raises(mx.ExportError, match="not plausible"):
        mx.build_glb(static, v, j)


def test_reader_rejects_junk():
    for bad in (b"", b"nope" * 10, b"glTF" + b"\0" * 30):
        with pytest.raises(mx.ExportError):
            mx.read_glb(bad)


def test_ac_nfr4_no_dashes_in_strings():
    for mod in (mx, avatar):
        tree = ast.parse(Path(mod.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and not node.value.startswith(("\n", " ")):
                assert "\u2014" not in node.value and "\u2013" not in node.value and " - " not in node.value, node.value


# real MHR asset (untrusted download in the HF cache, never committed): the layout check and the export on the real rig
MHR = next(iter(Path.home().glob(".cache/huggingface/hub/models--jetjodh--sam-3d-body-dinov3/snapshots/*/assets/mhr_model.pt")), None)


@pytest.mark.skipif(MHR is None or importlib.util.find_spec("torch") is None, reason="needs the MHR asset and torch")
def test_real_mhr_asset_layout_and_export():
    import torch

    mhr = torch.jit.load(str(MHR), map_location="cpu")
    with torch.no_grad():
        verts, state = mhr(torch.zeros(1, 45), torch.zeros(1, 204), torch.zeros(1, 72))
    static = mx.static_from_mhr(mhr)
    joints = state[0, :, :3].numpy() / 100
    res = mx.build_glb(static, verts[0].numpy() / 100, joints)
    assert 1.6 < res.height_m < 1.9 and len(res.mapped) == 22 and static.skin_idx.shape == (18439, 4)
    doc, blob = mx.read_glb(res.glb)
    assert len(doc["skins"][0]["joints"]) == 127 and len(blob) > 100000
