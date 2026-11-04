"""part2/autorig_weights.py and part2/autorig_reskin.py: an arm joins the body at the shoulder only (TICKET-058).

A picture of someone standing with the arms down gives a generated mesh whose hands are fused to the thighs. Before the
fix the limb split ramped the weights across that contact, so the thigh followed the hand and the hand the thigh: on
playback the hands stayed glued to the thighs. Spec: docs/specs/autorig.md (AC-24). No GPU: a synthetic figure with the
arms down and a strip of triangles fusing the left hand to the left thigh, as the generated mesh had."""
import json

import numpy as np
import pytest
from autorig_helpers import synthetic_parents as _parents
from test_autorig_weights import grid_box, join

from part2 import autorig_glb, autorig_pose, autorig_reskin, autorig_weights
from part2.autorig import MHR_INDEX, JOINTS

ARM = [MHR_INDEX[f"left{b}"] for b in ("UpperArm", "LowerArm", "Hand")]
LEG = [MHR_INDEX[f"left{b}"] for b in ("UpperLeg", "LowerLeg", "Foot", "Toes")]
BLEED = 0.4
LIMIT = 0.05
# joints of a figure with the arms hanging down: the left hand ends beside the left thigh
DOWN = {"hips": (0, 0.95, 0), "spine": (0, 1.1, 0), "chest": (0, 1.3, 0), "upperChest": (0, 1.4, 0), "neck": (0, 1.5, 0),
        "head": (0, 1.55, 0), "leftShoulder": (0.12, 1.45, 0), "leftUpperArm": (0.21, 1.45, 0),
        "leftLowerArm": (0.21, 1.20, 0), "leftHand": (0.21, 0.96, 0), "rightShoulder": (-0.12, 1.45, 0),
        "rightUpperArm": (-0.21, 1.45, 0), "rightLowerArm": (-0.21, 1.20, 0), "rightHand": (-0.21, 0.96, 0),
        "leftUpperLeg": (0.10, 0.90, 0), "leftLowerLeg": (0.10, 0.50, 0), "leftFoot": (0.10, 0.09, 0),
        "leftToes": (0.10, 0.03, 0.14), "rightUpperLeg": (-0.10, 0.90, 0), "rightLowerLeg": (-0.10, 0.50, 0),
        "rightFoot": (-0.10, 0.09, 0), "rightToes": (-0.10, 0.03, 0.14)}


# a finger joint under each hand, as MHR has, so the hand's bones reach into the hand
FINGERS = {"leftHand": (max(MHR_INDEX.values()) + 1, (0.21, 0.84, 0)), "rightHand": (max(MHR_INDEX.values()) + 2, (-0.21, 0.80, 0))}


def joints_down():
    j = np.tile(np.array(DOWN["hips"], float), (JOINTS, 1))
    for bone, i in MHR_INDEX.items():
        j[i] = DOWN[bone]
    for k, at in FINGERS.values():
        j[k] = at
    return j


def synthetic_parents():
    p = _parents()
    for hand, (k, _) in FINGERS.items():
        p[k] = MHR_INDEX[hand]
    return p


def fused_strip(x0=0.155, x1=0.185, y0=0.82, y1=0.90, rows=2):
    """Triangles joining the outer face of the left thigh to the inner face of the left hand at z = 0: the fused
    contact. Its corners fall on grid vertices of both boxes, so `figure` welds them into one surface."""
    ys = np.linspace(y0, y1, rows + 1)
    v = np.array([[x, y, 0.0] for y in ys for x in (x0, x1)])
    f = []
    for r in range(rows):
        a, b, c, d = 2 * r, 2 * r + 1, 2 * r + 2, 2 * r + 3
        f += [(a, b, d), (a, d, c)]
    return v, np.array(f)


BONE = {"thigh": "leftUpperLeg", "shin": "leftLowerLeg", "rleg": "rightUpperLeg", "torso": "spine", "upper": "leftUpperArm",
        "fore": "leftLowerArm", "hand": "leftHand", "rarm": "rightUpperArm", "rhand": "rightHand"}


def _weld(v, f, part):
    """One vertex per position (the first box keeps it), faces renumbered: the strip becomes part of the surface."""
    first, remap, keep = {}, np.zeros(len(v), dtype=np.int64), []
    for i, p in enumerate(map(tuple, np.round(v, 6))):
        if p not in first:
            first[p] = len(keep)
            keep.append(i)
        remap[i] = first[p]
    return v[keep], remap[f], part[keep]


def figure(fused=True, strip_faces=False):
    """(vertices, faces, part): legs, torso, arms hanging down and, when fused, the left hand welded to the left thigh
    by a strip of triangles over 8 cm. part names the box each vertex came from (a key of BONE). With strip_faces a
    fourth item flags the strip's faces."""
    boxes = [("thigh", grid_box((0.10, 0.70, 0), (0.11, 0.40, 0.11), 10)), ("shin", grid_box((0.10, 0.28, 0), (0.09, 0.44, 0.09), 4)),
             ("rleg", grid_box((-0.10, 0.48, 0), (0.11, 0.84, 0.11), 6)), ("torso", grid_box((0, 1.20, 0), (0.30, 0.50, 0.16), 6)),
             ("upper", grid_box((0.21, 1.33, 0), (0.07, 0.24, 0.07), 4)), ("fore", grid_box((0.21, 1.08, 0), (0.06, 0.24, 0.06), 4)),
             ("hand", grid_box((0.21, 0.90, 0), (0.05, 0.16, 0.04), 4)),
             ("rarm", grid_box((-0.21, 1.20, 0), (0.07, 0.48, 0.07), 4)), ("rhand", grid_box((-0.21, 0.88, 0), (0.05, 0.16, 0.04), 4))]
    parts = [b for _, b in boxes] + ([fused_strip()] if fused else [])
    names = [n for n, _ in boxes] + (["strip"] if fused else [])
    v, f = join(parts)
    part = np.concatenate([[n] * len(b[0]) for n, b in zip(names, parts)])
    flags = np.zeros(len(f), dtype=bool)
    if fused:
        flags[-len(parts[-1][1]):] = True
    v, f, part = _weld(v, f, part)
    assert not (part == "strip").any()  # every strip corner is a thigh or a hand vertex
    return (v, f, part, flags) if strip_faces else (v, f, part)


def bled_skin(v, part):
    """Each box follows its own bone, the torso's top corners share 0.3 with the upper arms (the shoulder junction), and
    across the contact the thigh by the hand takes 0.4 of the hand and the hand's inner side 0.4 of the thigh, as the
    nearest-body-vertex transfer gave the generated mesh."""
    idx = np.zeros((len(v), 4), dtype=np.int64)
    w = np.zeros((len(v), 4))
    idx[:, 0] = [MHR_INDEX[BONE[p]] for p in part]
    w[:, 0] = 1.0
    shoulder = (part == "torso") & (v[:, 1] > 1.40) & (np.abs(v[:, 0]) > 0.12)
    idx[shoulder, 1] = np.where(v[shoulder, 0] > 0, MHR_INDEX["leftUpperArm"], MHR_INDEX["rightUpperArm"])
    w[shoulder, 0], w[shoulder, 1] = 0.7, 0.3
    thigh_by_hand = (part == "thigh") & (v[:, 0] > 0.14) & (v[:, 1] > 0.80)
    hand_inner = (part == "hand") & (v[:, 0] < 0.20)
    for rows, own, other in ((thigh_by_hand, "leftUpperLeg", "leftHand"), (hand_inner, "leftHand", "leftUpperLeg")):
        idx[rows, 0], idx[rows, 1] = MHR_INDEX[own], MHR_INDEX[other]
        w[rows, 0], w[rows, 1] = 1 - BLEED, BLEED
    return idx, w


def mass(idx, w, joints):
    return (w * np.isin(idx, joints)).sum(1)


def refine(v, f, idx, w):
    return autorig_weights.refine(v, f, joints_down(), synthetic_parents(), dict(MHR_INDEX), idx, w)


def test_the_contact_bleed_is_there_before():
    v, _, part = figure()
    idx, w = bled_skin(v, part)
    assert mass(idx, w, ARM)[part == "thigh"].max() == pytest.approx(BLEED)  # the file's skin before the split
    assert mass(idx, w, LEG)[part == "hand"].max() == pytest.approx(BLEED)


def test_no_thigh_vertex_keeps_the_hands_weight_and_no_hand_vertex_the_thighs():
    v, f, part = figure()
    ni, nw = refine(v, f, *bled_skin(v, part))
    assert mass(ni, nw, ARM)[part == "thigh"].max() <= LIMIT
    assert mass(ni, nw, LEG)[part == "hand"].max() <= LIMIT
    assert mass(ni, nw, ARM)[part == "hand"].min() > 1 - LIMIT  # the hand still follows its own arm


def test_a_torso_vertex_by_the_shoulder_may_keep_the_arm_but_not_one_by_the_waist():
    v, f, part = figure(fused=False)
    j, mapping = joints_down(), dict(MHR_INDEX)
    limb = autorig_weights.joint_limbs(synthetic_parents(), mapping)
    reach = autorig_weights.arm_reach(v, j, mapping)
    torso = np.full(len(v), autorig_weights.TORSO)
    ok = autorig_weights.arm_allowed(limb, torso, reach)
    shoulder = np.argmin(np.linalg.norm(v - [0.15, 1.45, 0.08], axis=1))
    waist = np.argmin(np.linalg.norm(v - [0.15, 0.95, 0.08], axis=1))
    assert ok[shoulder, ARM].all() and not ok[waist, ARM].any()  # the junction still ramps (AC-20), the waist never
    idx, w = bled_skin(v, part)
    hip = (part == "torso") & (v[:, 1] < 1.0) & (v[:, 0] > 0.12)  # a hand resting on the hip left 0.4 of it here
    idx[hip, 1], w[hip, 0], w[hip, 1] = MHR_INDEX["leftHand"], 1 - BLEED, BLEED
    ni, nw = refine(v, f, idx, w)
    assert hip.any() and mass(ni, nw, ARM)[hip].max() <= LIMIT


def test_a_hand_resting_on_the_waist_keeps_no_torso_weight():
    """Review B2: an arm vertex away from the shoulder kept spine weight and stretched into a shard by the hip."""
    v, f, part = figure()
    idx, w = bled_skin(v, part)
    on_waist = part == "hand"
    idx[on_waist, 2], w[on_waist, 2] = MHR_INDEX["spine"], 0.3
    w[on_waist] /= w[on_waist].sum(1, keepdims=True)
    torso = [MHR_INDEX[b] for b in ("hips", "spine", "chest", "upperChest")]
    assert mass(idx, w, torso)[on_waist].min() > 0.2
    ni, nw = refine(v, f, idx, w)
    assert mass(ni, nw, torso)[on_waist].max() <= LIMIT and mass(ni, nw, ARM)[on_waist].min() > 1 - LIMIT


@pytest.mark.skip(reason="shard drop off since re-review round 4 (B1-r4, TICKET-058): DROP_SHARDS = False")
def test_a_piece_of_thigh_given_to_the_hand_is_dropped_not_left_to_fly():
    """Review B2: thigh surface the transfer gave to the hand is joined to the thigh only through the contact; the cut
    breaks it loose, and a piece all arm, away from the shoulder and off the arm's bones is dropped, not left to fly
    beside the hand. The hand itself, on its bones, stays."""
    v, f, part = figure()
    idx, w = bled_skin(v, part)
    scale = (part == "thigh") & (v[:, 2] > 0.054) & (np.abs(v[:, 0] - 0.10) < 0.025) & (np.abs(v[:, 1] - 0.70) < 0.05)
    idx[scale, 0], w[scale] = MHR_INDEX["leftHand"], [1.0, 0, 0, 0]
    inside = np.isin(f, np.where(scale)[0]).all(1)
    assert scale.sum() >= 9 and inside.any()
    kept, cut = autorig_weights.cut_bridges(v, f, joints_down(), synthetic_parents(), dict(MHR_INDEX), idx, w)
    left = {tuple(t) for t in kept}
    assert not any(tuple(t) in left for t in f[inside])
    assert all(tuple(t) in left for t in f[(part[f] == "hand").all(1)])


def _staff(kind: str):
    """(vertices, faces, idx, w, body faces) of the figure with a staff 60 cm long held in the left hand, as the
    reviewers' probes built it: "separate" (all hand weight), "big" (its lowest vertices given the leg, the tip on the
    thigh) and "mid" (a band across the thigh given the leg, the staff crossing it). A dense back plate keeps the
    3 percent cap from binding."""
    v, f, part = figure(fused=False)
    back_v, back_f = grid_box((0, 1.20, -0.2), (0.30, 0.50, 0.02), 30)
    v, f = join([(v, f), (back_v, back_f)])
    part = np.concatenate([part, ["torso"] * len(back_v)])
    sv, sf = grid_box((0.21, 0.60, 0.06), (0.02, 0.60, 0.02), 8)
    v2, f2 = join([(v, f), (sv, sf)])
    part2 = np.concatenate([part, ["staff"] * len(sv)])
    idx, w = bled_skin(v2, np.where(part2 == "staff", "hand", part2))
    band = {"separate": np.zeros(len(v2), dtype=bool), "big": v2[:, 1] < 0.35,
            "mid": (v2[:, 1] > 0.30) & (v2[:, 1] < 0.42)}[kind]
    idx[(part2 == "staff") & band, 0] = MHR_INDEX["leftUpperLeg"]
    return v2, f2, idx, w, len(f)


@pytest.mark.parametrize("kind", ["separate", "big", "mid"])
def test_the_cut_removes_the_contact_triangles_and_no_other_face(kind):
    """Re-review round 4 (B1-r4): with the shard drop off, a staff held in the hand, separate, tipped on the thigh or
    crossing it, loses only the triangles across its own contact; every other face of the model stays."""
    v, f, idx, w, body = _staff(kind)
    mapping, j, parents = dict(MHR_INDEX), joints_down(), synthetic_parents()
    limb = autorig_weights.joint_limbs(parents, mapping)
    dist, _ = autorig_weights.limb_distances(v, j, parents, limb)
    vl, _ = autorig_weights.vertex_limbs(idx, w, limb, dist)
    reach = autorig_weights.arm_reach(v, j, mapping)
    contact = np.zeros(len(f), dtype=bool)
    for a, b in ((0, 1), (1, 2), (2, 0)):
        contact |= autorig_weights.contact_edges(f[:, [a, b]], vl, reach)
    report = {}
    kept, cut = autorig_weights.cut_bridges(v, f, j, parents, mapping, idx, w, report)
    assert len(kept) == len(f) - contact.sum() and cut == contact.sum()
    left = {tuple(t) for t in kept}
    assert all(tuple(t) in left for t in f[~contact])
    assert report["shards_dropped"] is False and report["shard_faces"] >= 0
    assert (kind == "separate") == (not contact[body:].any())


def test_contact_edges_are_the_strip_not_the_shoulder():
    v, f, part, strip = figure(strip_faces=True)
    idx, w = bled_skin(v, part)
    limb = autorig_weights.joint_limbs(synthetic_parents(), dict(MHR_INDEX))
    dist, _ = autorig_weights.limb_distances(v, joints_down(), synthetic_parents(), limb)
    vl, _ = autorig_weights.vertex_limbs(idx, w, limb, dist)
    edges = autorig_pose.unique_edges(f)
    contact = autorig_weights.contact_edges(edges, vl, autorig_weights.arm_reach(v, joints_down(), dict(MHR_INDEX)))
    on_strip = {tuple(sorted(e)) for t in f[strip] for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))}
    crossing = np.array([tuple(sorted(e)) in on_strip and part[e[0]] != part[e[1]] for e in edges])
    assert contact[crossing].all() and crossing.any()
    assert not contact[(v[edges][:, :, 1] > 1.3).all(1)].any()  # nothing by the shoulder is contact


def test_cut_bridges_cuts_the_fused_strip_whatever_the_stretch(monkeypatch):
    monkeypatch.setattr(autorig_weights, "CUT_STRETCH", 1e9)  # no test pose stretch can cut: only the contact rule does
    v, f, part, strip = figure(strip_faces=True)
    ni, nw = refine(v, f, *bled_skin(v, part))
    kept, cut = autorig_weights.cut_bridges(v, f, joints_down(), synthetic_parents(), dict(MHR_INDEX), ni, nw)
    strip_faces = strip
    assert cut > 0 and len(kept) == len(f) - cut
    left = {tuple(t) for t in kept}
    assert sum(tuple(t) in left for t in f[strip_faces]) < strip_faces.sum() / 2
    assert all(tuple(t) in left for t in f[(part[f] == "thigh").all(1)])  # the thigh's own surface is whole


def test_a_figure_with_no_contact_is_not_cut():
    v, f, part = figure(fused=False)
    ni, nw = refine(v, f, *bled_skin(v, part))
    kept, cut = autorig_weights.cut_bridges(v, f, joints_down(), synthetic_parents(), dict(MHR_INDEX), ni, nw)
    assert cut == 0 and np.array_equal(kept, f)


# ---- reskin: an already written GLB ------------------------------------------------------------------------

def written_glb(v, f, idx, w):
    names = [next((n for n, i in MHR_INDEX.items() if i == k), f"mhr_{k}") for k in range(JOINTS)]
    mesh = type("M", (), {"vertices": v, "faces": f, "colors": None})()
    return autorig_glb.build(mesh, joints_down(), synthetic_parents(), names, idx, w,
                             {"copyright": "test", "licence": "test"})


def swing(rig, deg=-70):
    """Posed vertices with the left arm swung forward by `deg` about X at the shoulder; the hand joint's new place."""
    rot = {rig["mapping"]["leftUpperArm"]: autorig_pose.rot_x(deg)}
    posed = autorig_pose.pose_vertices(rig["vertices"], rig["joints"], rig["parents"], rig["idx"], rig["w"], rot)
    j = rig["joints"]
    s, h = j[rig["mapping"]["leftUpperArm"]], j[rig["mapping"]["leftHand"]]
    return posed, s + autorig_pose.rot_x(deg) @ (h - s)


def test_reskin_frees_the_hand_of_a_file_written_before_the_fix():
    v, f, part = figure()
    idx, w = bled_skin(v, part)  # the file as the old split left it: weight shared across the contact
    old = written_glb(v, f, idx, w)
    new, report = autorig_reskin.reskin(old)
    before, after = autorig_pose.read_rig(old), autorig_pose.read_rig(new)
    hand, thigh = part == "hand", part == "thigh"
    posed_old, hand_at = swing(before)
    posed_new, _ = swing(after)
    rest_offset = np.linalg.norm(v[hand] - joints_down()[MHR_INDEX["leftHand"]], axis=1)
    # before: the inner side of the hand stays back toward the thigh; after: the whole hand travels with the hand joint
    assert np.abs(np.linalg.norm(posed_old[hand] - hand_at, axis=1) - rest_offset).max() > 0.05
    assert np.abs(np.linalg.norm(posed_new[hand] - hand_at, axis=1) - rest_offset).max() < 0.01
    assert np.linalg.norm(posed_new[thigh] - v[thigh], axis=1).max() < 0.01  # and the thigh stays where it was
    assert report["changed"] and report["bridging_triangles_cut"] > 0 and report["triangles"] == len(f) - report["bridging_triangles_cut"]


def test_reskin_changes_only_the_skin_and_the_triangles():
    v, f, part = figure()
    old = written_glb(v, f, *bled_skin(v, part))
    new, _ = autorig_reskin.reskin(old)
    a, b = autorig_pose.read_rig(old), autorig_pose.read_rig(new)
    assert np.array_equal(a["vertices"], b["vertices"]) and np.array_equal(a["joints"], b["joints"])
    assert np.array_equal(a["parents"], b["parents"]) and a["mapping"] == b["mapping"]
    assert np.allclose(b["w"].sum(1), 1, atol=1e-5) and (b["w"] >= 0).all()
    doc_a, doc_b = a["doc"], b["doc"]
    assert doc_a["nodes"] == doc_b["nodes"] and doc_a["asset"] == doc_b["asset"] and doc_a["bufferViews"] == doc_b["bufferViews"]
    assert autorig_reskin.reskin(new)[0] == autorig_reskin.reskin(new)[0]  # deterministic


def test_reskin_refuses_a_file_autorig_did_not_write(tmp_path, capsys):
    v, f, part = figure(fused=False)
    glb = bytearray(written_glb(v, f, *bled_skin(v, part)))
    doc, _ = autorig_glb.read(bytes(glb))
    doc["asset"]["generator"] = "someone else"
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    with pytest.raises(autorig_reskin.ReskinError):
        autorig_reskin.reskin(autorig_glb._pack(doc, autorig_reskin._binary(bytes(glb))))
    with pytest.raises(autorig_reskin.ReskinError):
        autorig_reskin.reskin(b"not a glb at all")
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"glTF nope")
    assert autorig_reskin.command(bad, tmp_path / "out.glb") == 2 and not (tmp_path / "out.glb").exists()
    assert "part2:" in capsys.readouterr().err


def test_reskin_command_writes_the_file_and_the_report(tmp_path, capsys):
    v, f, part = figure()
    src = tmp_path / "model.glb"
    src.write_bytes(written_glb(v, f, *bled_skin(v, part)))
    assert autorig_reskin.command(src, src) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["changed"] and autorig_pose.read_rig(src.read_bytes())["faces"].shape[0] == report["triangles"]
    assert not (tmp_path / "model.glb.part").exists()
