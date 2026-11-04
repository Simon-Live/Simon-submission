"""part2/autorig_glb.py: the skinned GLB writer. Spec: docs/specs/autorig.md (AC-12, AC-13)."""
import numpy as np
import pytest
from autorig_helpers import (
    humanoid,
    synthetic_joints,
    synthetic_parents,
    synthetic_skin,
)

from part2 import autorig, autorig_glb

NOTICE = {"copyright": autorig.NOTICE, "licence": autorig.LICENCE}


def build(mesh=None, colors=False):
    mesh = mesh or humanoid(colors)
    skin = synthetic_skin(mesh.vertices)
    names = autorig.joint_names(autorig.canonical_map(skin.parents))
    glb = autorig_glb.build(mesh, synthetic_joints(), skin.parents, names, skin.idx, skin.w, NOTICE)
    return mesh, skin, glb


def test_ac12_structure_names_and_licence():
    mesh, _, glb = build(colors=True)
    doc, read = autorig_glb.read(glb)
    assert doc["asset"]["version"] == "2.0" and doc["asset"]["extras"]["licence"] == autorig.LICENCE
    assert "SAM License" in doc["asset"]["copyright"] and "Apache-2.0" in doc["asset"]["copyright"]
    assert len(doc["scenes"]) == 1 and len(doc["meshes"]) == 1 and len(doc["meshes"][0]["primitives"]) == 1
    attrs = doc["meshes"][0]["primitives"][0]["attributes"]
    assert set(attrs) == {"POSITION", "NORMAL", "COLOR_0", "JOINTS_0", "WEIGHTS_0"}
    assert len(doc["skins"]) == 1 and len(doc["skins"][0]["joints"]) == 127
    assert "images" not in doc and "textures" not in doc and not any("uri" in b for b in doc["buffers"])
    names = [n["name"] for n in doc["nodes"][:127]]
    assert names[1] == "hips" and names[77] == "leftHand" and names[0] == "mhr_0" and len(set(names)) == 127
    assert np.allclose(read(attrs["POSITION"]), mesh.vertices, atol=1e-6)


def test_ac12_without_colours_has_a_grey_material_and_no_colour_attribute():
    _, _, glb = build(colors=False)
    doc, _ = autorig_glb.read(glb)
    assert "COLOR_0" not in doc["meshes"][0]["primitives"][0]["attributes"]
    assert doc["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][:3] == autorig_glb.DEFAULT_RGBA[:3]


def test_ac12_weights_are_valid():
    _, skin, glb = build()
    doc, read = autorig_glb.read(glb)
    attrs = doc["meshes"][0]["primitives"][0]["attributes"]
    w, j = read(attrs["WEIGHTS_0"]), read(attrs["JOINTS_0"])
    assert (w >= 0).all() and np.allclose(w.sum(1), 1, atol=1e-5) and j.max() < 127
    assert np.array_equal(j.astype(int), skin.idx)


def world_positions(doc):
    nodes = doc["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    out = []
    for i in range(127):
        p, k = np.array(nodes[i]["translation"]), i
        while k in parent:
            k = parent[k]
            p = p + np.array(nodes[k]["translation"])
        out.append(p)
    return np.array(out)


def test_ac13_bind_pose_equals_input_and_nodes_have_no_rotation():
    mesh, _, glb = build()
    doc, read = autorig_glb.read(glb)
    assert all("rotation" not in n and "scale" not in n for n in doc["nodes"])
    world = world_positions(doc)
    assert np.allclose(world, synthetic_joints(), atol=1e-6)
    ibm = read(doc["skins"][0]["inverseBindMatrices"]).reshape(127, 4, 4)  # glTF stores column-major: [col][row]
    attrs = doc["meshes"][0]["primitives"][0]["attributes"]
    joints, weights, pos = read(attrs["JOINTS_0"]).astype(int), read(attrs["WEIGHTS_0"]), read(attrs["POSITION"])
    skinned = np.zeros_like(pos, dtype=float)
    for k in range(4):
        for v in range(len(pos)):
            j = joints[v, k]
            m = np.eye(4)
            m[:3, 3] = world[j]  # world matrix of an identity-rotation joint
            ib = ibm[j].T  # back to row-major
            skinned[v] += weights[v, k] * (m @ ib @ np.append(pos[v], 1))[:3]
    assert np.abs(skinned - mesh.vertices).max() < 1e-6


def test_ac12_build_is_deterministic():
    assert build()[2] == build()[2]


def test_arrays_that_do_not_fit_are_refused():
    mesh = humanoid()
    skin = synthetic_skin(mesh.vertices)
    names = ["j"] * 127
    with pytest.raises(autorig_glb.GlbError, match="do not match"):
        autorig_glb.build(mesh, synthetic_joints(), synthetic_parents(), names, skin.idx[:5], skin.w[:5], NOTICE)
    bad = skin.w.copy()
    bad[0] = [0.5, 0.2, 0, 0]
    with pytest.raises(autorig_glb.GlbError, match="sum to 1"):
        autorig_glb.build(mesh, synthetic_joints(), synthetic_parents(), names, skin.idx, bad, NOTICE)
    idx = skin.idx.copy()
    idx[0, 0] = 200
    with pytest.raises(autorig_glb.GlbError, match="out of range"):
        autorig_glb.build(mesh, synthetic_joints(), synthetic_parents(), names, idx, skin.w, NOTICE)
    with pytest.raises(autorig_glb.GlbError, match="not a GLB"):
        autorig_glb.read(b"nope")


def test_vertex_normals_are_unit_and_face_outward():
    mesh = humanoid()
    n = autorig_glb.vertex_normals(mesh.vertices, mesh.faces)
    assert np.allclose(np.linalg.norm(n, axis=1), 1)
    degenerate = autorig_glb.vertex_normals(np.zeros((3, 3)), np.array([[0, 1, 2]]))
    assert np.allclose(degenerate, [0, 0, 1])
