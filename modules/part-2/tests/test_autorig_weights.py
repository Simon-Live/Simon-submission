"""part2/autorig_weights.py and part2/autorig_pose.py: skin weights that do not bleed between limbs, and the stretch
metric. Spec: docs/specs/autorig.md (AC-20, AC-21). No GPU, torch or scipy: a synthetic two-leg mesh and skeleton."""
import numpy as np
import pytest
from autorig_helpers import JOINT_AT, synthetic_joints, synthetic_parents

from part2 import autorig_pose, autorig_weights
from part2.autorig import MHR_INDEX

LEFT, RIGHT = MHR_INDEX["leftUpperLeg"], MHR_INDEX["rightUpperLeg"]
LEG_JOINTS = {side: [MHR_INDEX[f"{side}{b}"] for b in ("UpperLeg", "LowerLeg", "Foot", "Toes")] for side in ("left", "right")}
BLEED = 0.4          # the weight an inner-thigh vertex takes from the other leg before the fix
THRESHOLD = 0.05     # after the fix no leg vertex may carry more than this on the other leg


def grid_box(centre, size, n=4):
    """(vertices, faces): a box surface cut into n x n quads a side, corners shared."""
    c, s = np.array(centre, float), np.array(size, float) / 2
    verts, faces, seen = [], [], {}

    def vid(p):
        key = tuple(np.round(p, 6))
        if key not in seen:
            seen[key] = len(verts)
            verts.append(p)
        return seen[key]

    for axis in range(3):
        a, b = [k for k in range(3) if k != axis]
        for sign in (-1, 1):
            for i in range(n):
                for j in range(n):
                    quad = []
                    for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        p = c.copy()
                        p[axis] += sign * s[axis]
                        p[a] += (-1 + 2 * (i + di) / n) * s[a]
                        p[b] += (-1 + 2 * (j + dj) / n) * s[b]
                        quad.append(vid(p))
                    faces += [(quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])]
    return np.array(verts), np.array(faces)


def join(parts):
    verts, faces, base = [], [], 0
    for v, f in parts:
        verts.append(v)
        faces.append(f + base)
        base += len(v)
    return np.concatenate(verts), np.concatenate(faces)


def web(left_x=0.055, right_x=-0.055, y0=0.70, y1=0.88, rows=4):
    """A strip of faces joining the inner sides of the two legs, as a belt, a pouch or a fused crotch does."""
    ys = np.linspace(y0, y1, rows + 1)
    v = np.array([[x, y, 0.0] for y in ys for x in (left_x, right_x)])
    f = []
    for r in range(rows):
        a, b, c, d = 2 * r, 2 * r + 1, 2 * r + 2, 2 * r + 3
        f += [(a, b, d), (a, d, c)]
    return v, np.array(f)


def two_leg_mesh(with_web=False):
    parts = [grid_box((0.10, 0.45, 0), (0.09, 0.90, 0.09), 8), grid_box((-0.10, 0.45, 0), (0.09, 0.90, 0.09), 8),
             grid_box((0, 1.15, 0), (0.34, 0.5, 0.16), 6)]
    if with_web:
        parts.append(web())
    return join(parts)


def bleeding_skin(vertices):
    """Each vertex follows its nearest canonical joint (0.6) and the next (0.4) ... except inner-thigh vertices, which take
    the 0.4 from the other leg's upper-leg joint: the nearest-body-vertex bleed."""
    idx = np.array(sorted(MHR_INDEX.values()))
    pos = synthetic_joints()[idx]
    order = np.argsort(np.linalg.norm(vertices[:, None] - pos[None], axis=2), axis=1)[:, :2]
    out_i = np.zeros((len(vertices), 4), dtype=np.int64)
    out_w = np.zeros((len(vertices), 4))
    out_i[:, 0], out_i[:, 1] = idx[order[:, 0]], idx[order[:, 1]]
    out_w[:, 0], out_w[:, 1] = 1 - BLEED, BLEED
    inner = (np.abs(vertices[:, 0]) < 0.10) & (vertices[:, 1] < 0.9)
    out_i[inner & (vertices[:, 0] > 0), 1] = RIGHT
    out_i[inner & (vertices[:, 0] < 0), 1] = LEFT
    return out_i, out_w


def leg_mass(idx, w, joints):
    return (w * np.isin(idx, joints)).sum(1)


@pytest.fixture(scope="module")
def mesh():
    return two_leg_mesh()


def refine(vertices, faces, idx, w, **kw):
    return autorig_weights.refine(vertices, faces, synthetic_joints(), synthetic_parents(), dict(MHR_INDEX), idx, w, **kw)


def test_the_bleed_is_there_before(mesh):
    v, _ = mesh
    idx, w = bleeding_skin(v)
    left_leg = (v[:, 0] > 0.02) & (v[:, 1] < 0.85)
    assert leg_mass(idx, w, LEG_JOINTS["right"])[left_leg].max() == pytest.approx(BLEED)


def test_no_leg_vertex_takes_the_other_legs_weight(mesh):
    v, f = mesh
    idx, w = bleeding_skin(v)
    ni, nw = refine(v, f, idx, w)
    left_leg, right_leg = (v[:, 0] > 0.02) & (v[:, 1] < 0.85), (v[:, 0] < -0.02) & (v[:, 1] < 0.85)
    assert leg_mass(ni, nw, LEG_JOINTS["right"])[left_leg].max() <= THRESHOLD
    assert leg_mass(ni, nw, LEG_JOINTS["left"])[right_leg].max() <= THRESHOLD
    assert leg_mass(ni, nw, LEG_JOINTS["left"])[left_leg].min() > 0.3  # and the leg still follows its own leg


def test_rows_are_valid_skin_weights(mesh):
    v, f = mesh
    ni, nw = refine(v, f, *bleeding_skin(v))
    assert ni.shape == nw.shape == (len(v), 4)
    assert (nw >= 0).all() and np.allclose(nw.sum(1), 1) and ni.min() >= 0 and ni.max() < 127


def test_refine_is_deterministic(mesh):
    v, f = mesh
    a, b = refine(v, f, *bleeding_skin(v)), refine(v, f, *bleeding_skin(v))
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_a_torso_vertex_keeps_one_leg_only(mesh):
    v, f = mesh
    idx, w = bleeding_skin(v)
    torso = (v[:, 1] > 0.95) & (np.abs(v[:, 0]) > 0.01)
    idx[torso, 2] = np.where(v[torso, 0] > 0, RIGHT, LEFT)  # a leg weight from the wrong side
    w[torso, 2], w[torso, 0] = 0.2, w[torso, 0] - 0.2
    ni, nw = refine(v, f, idx, w)
    for side, other in (("left", "right"), ("right", "left")):
        rows = torso & ((v[:, 0] > 0) == (side == "left"))
        assert leg_mass(ni, nw, LEG_JOINTS[other])[rows].max() <= THRESHOLD


def test_an_arm_vertex_loses_a_leg_weight():
    v, f = grid_box((0.5, 1.45, 0), (0.4, 0.07, 0.07), 6)
    idx = np.tile([MHR_INDEX["leftUpperArm"], MHR_INDEX["leftLowerArm"], LEFT, 0], (len(v), 1))
    w = np.tile([0.5, 0.3, 0.2, 0.0], (len(v), 1))
    ni, nw = refine(v, f, idx, w)
    assert leg_mass(ni, nw, LEG_JOINTS["left"] + LEG_JOINTS["right"]).max() <= THRESHOLD


def test_a_vertex_with_only_the_wrong_limbs_weight_follows_its_bone():
    v, f = grid_box((0.10, 0.45, 0), (0.09, 0.90, 0.09), 8)
    idx = np.tile([RIGHT, 0, 0, 0], (len(v), 1))  # every vertex carries only the other leg
    w = np.tile([1.0, 0, 0, 0], (len(v), 1))
    ni, nw = refine(v, f, idx, w)
    assert leg_mass(ni, nw, LEG_JOINTS["left"]).min() > 0.99


# ---- the stretch metric -------------------------------------------------------------------------------

def test_pose_vertices_is_the_bind_with_no_rotation(mesh):
    v, _ = mesh
    idx, w = bleeding_skin(v)
    assert np.allclose(autorig_pose.pose_vertices(v, synthetic_joints(), synthetic_parents(), idx, w, {}), v)


def test_a_rotation_turns_a_rigid_leg_about_its_joint():
    v = np.array([[0.1, 0.5, 0.0], [0.1, 0.9, 0.0]])
    idx = np.tile([LEFT, 0, 0, 0], (2, 1))
    w = np.tile([1.0, 0, 0, 0], (2, 1))
    posed = autorig_pose.pose_vertices(v, synthetic_joints(), synthetic_parents(), idx, w, {LEFT: autorig_pose.rot_x(90)})
    assert posed[1] == pytest.approx(v[1])  # the hip joint is at y = 0.9
    assert posed[0] == pytest.approx([0.1, 0.9, -0.4])  # the leg points down; a 90 degree turn about X swings it back


def test_edge_stretch_reads_a_stretched_edge():
    bind = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0.0]])
    posed = bind * np.array([3.0, 1, 1])
    s = autorig_pose.edge_stretch(bind, posed, np.array([[0, 1, 2]]))
    assert s["max"] == pytest.approx(3.0) and s["edges"] == 3 and s["over_3x"] == 0


def test_the_split_cuts_the_leg_stretch_of_a_mesh_with_a_web():
    v, f = two_leg_mesh(with_web=True)
    idx, w = bleeding_skin(v)
    args = (v, f, synthetic_joints(), synthetic_parents())
    before = autorig_pose.pose_stretch(*args, idx, w, MHR_INDEX)["legs"]
    ni, nw = refine(v, f, idx, w)
    after = autorig_pose.pose_stretch(*args, ni, nw, MHR_INDEX)["legs"]
    assert after["max"] < before["max"] and after["over_3x"] <= before["over_3x"]


def test_the_web_ramps_between_the_legs_not_tears(mesh):
    v, f = two_leg_mesh(with_web=True)
    ni, nw = refine(v, f, *bleeding_skin(v))
    middle = (np.abs(v[:, 0]) < 0.06) & (v[:, 2] == 0) & (v[:, 1] > 0.7) & (v[:, 1] < 0.88)
    assert middle.any()
    below = (v[:, 1] < 0.4) & (np.abs(v[:, 0]) > 0.02)
    assert leg_mass(ni, nw, LEG_JOINTS["right"] + LEG_JOINTS["left"])[below].min() > 0.9
    assert leg_mass(ni, nw, LEG_JOINTS["right"])[(v[:, 0] > 0.02) & below].max() <= THRESHOLD


def test_read_rig_gives_back_what_autorig_wrote():
    from autorig_helpers import fake_fit_body, humanoid, synthetic_skin

    from part2 import autorig, autorig_mesh

    m = autorig_mesh.normalize(humanoid(colors=True))[0]
    rigged = autorig.rig(m, synthetic_skin(m.vertices), fake_fit_body(), "abc")
    r = autorig_pose.read_rig(rigged.glb)
    assert r["vertices"].shape == m.vertices.shape and r["joints"].shape == (127, 3) and len(r["mapping"]) == 22
    assert np.allclose(r["w"].sum(1), 1, atol=1e-5)
    assert set(rigged.avatar["stretch"]) == {"before", "after", "cut"} and set(rigged.avatar["stretch"]["after"]) == {"legs", "arms"}
    assert JOINT_AT["hips"][1] == pytest.approx(r["joints"][r["mapping"]["hips"]][1], abs=0.2)


# ---- bridging triangles -------------------------------------------------------------------------------

def hard_split_skin(v):
    """Every vertex follows its own leg's upper-leg joint (the torso box follows the hips): a hard split, no ramp."""
    idx = np.zeros((len(v), 4), dtype=np.int64)
    idx[:, 0] = np.where(v[:, 1] > 0.9, MHR_INDEX["hips"], np.where(v[:, 0] > 0, LEFT, RIGHT))
    w = np.zeros((len(v), 4))
    w[:, 0] = 1.0
    return idx, w


def test_cut_bridges_removes_the_web_between_the_legs_and_keeps_the_rest(monkeypatch):
    monkeypatch.setattr(autorig_weights, "CUT_STRETCH", 1.8)  # this web is 11 cm wide, so it only stretches about 2.5x
    v, f = two_leg_mesh(with_web=True)
    idx, w = hard_split_skin(v)
    args = (synthetic_joints(), synthetic_parents(), idx, w, MHR_INDEX)
    before = autorig_pose.pose_stretch(v, f, *args)["legs"]
    kept, cut = autorig_weights.cut_bridges(v, f, synthetic_joints(), synthetic_parents(), dict(MHR_INDEX), idx, w)
    web_faces = np.where(f.max(1) >= len(v) - 10)[0]
    assert before["max"] > autorig_weights.CUT_STRETCH
    assert 0 < cut <= len(web_faces) and len(kept) == len(f) - cut
    assert autorig_pose.pose_stretch(v, kept, *args)["legs"]["max"] < before["max"]


def test_cut_bridges_leaves_a_mesh_with_no_bridge_alone(mesh):
    v, f = mesh
    idx, w = hard_split_skin(v)
    kept, cut = autorig_weights.cut_bridges(v, f, synthetic_joints(), synthetic_parents(), dict(MHR_INDEX), idx, w)
    assert cut == 0 and np.array_equal(kept, f)


def test_cut_bridges_refuses_to_cut_more_than_the_share(monkeypatch):
    v, f = two_leg_mesh(with_web=True)
    idx, w = hard_split_skin(v)
    monkeypatch.setattr(autorig_weights, "CUT_MAX_SHARE", 0.0)
    kept, cut = autorig_weights.cut_bridges(v, f, synthetic_joints(), synthetic_parents(), dict(MHR_INDEX), idx, w)
    assert cut == 0 and np.array_equal(kept, f)
