"""Lifter B2 `bones-prior` (docs/specs/backends-gpu-cpu.md "Lifter B2, bones-prior", AC-BP01 to AC-BP08; TICKET-044).
Synthetic people projected through a known K; no model, no fixture."""
import json
import subprocess
import sys
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from test_cpu_rtm import Fake2D, _frames
from test_lifter_fixed_bones import SIZE, K, _observe, _rot_y, _unit, skeleton

from part2 import lifters, stamp
from part2.backends import cpu_rtm
from part2.joints import CANONICAL
from part2.lifters import BODY_BONES, J, bone_cv, bone_lengths, project, rays
from part2.lifters import bones_prior as bp
from part2.lifters import fixed_bones as fb

ROOT = Path(__file__).resolve().parent.parent
X, Y, Z = np.eye(3)  # body axes: x left, y up, z front
DOWN = -Y


def _lengths():
    """Segment lengths of test_lifter_fixed_bones.skeleton: fb.RATIO scaled to a standing chain of fb.H_REF."""
    L = dict(zip(fb.SEGMENTS, fb.RATIO * fb.H_REF / fb.RATIO[fb.CHAIN].sum()))
    for a, b in fb.PAIRS:
        L[a] = L[b] = (L[a] + L[b]) / 2
    return L


def pose(thigh, shank, upper, fore, yaw_deg=0.0, depth=4.0):
    """One person (17, 3) in the OpenCV camera frame, upright trunk; limb directions per side ("left", "right") in
    body axes (x left, y up, z front). yaw 0 faces the camera; 90 shows the left side."""
    L = _lengths()
    sw, hw, torso = L[("left_shoulder", "right_shoulder")], L[("left_hip", "right_hip")], L[("shoulder_mid", "hip_mid")]
    P = {"left_hip": hw / 2 * X, "right_hip": -hw / 2 * X,
         "left_shoulder": sw / 2 * X + torso * Y, "right_shoulder": -sw / 2 * X + torso * Y}
    P["nose"] = torso * Y + L[("nose", "shoulder_mid")] * _unit(0.85 * Y + 0.5 * Z)
    for side, sx in (("left", 1), ("right", -1)):
        P[f"{side}_eye"] = P["nose"] + 0.03 * sx * X + 0.03 * Y - 0.02 * Z
        P[f"{side}_ear"] = P["nose"] + 0.07 * sx * X + 0.01 * Y - 0.09 * Z
        for a, b, d in ((f"{side}_hip", f"{side}_knee", thigh), (f"{side}_knee", f"{side}_ankle", shank),
                        (f"{side}_shoulder", f"{side}_elbow", upper), (f"{side}_elbow", f"{side}_wrist", fore)):
            P[b] = P[a] + L[(a, b)] * _unit(np.asarray(d[side], float))
    body = np.array([P[name] for name in J])
    R = np.diag([1.0, -1.0, -1.0]) @ _rot_y(np.radians(yaw_deg))
    return body @ R.T + np.array([0.2, 0.1, depth])


def both(v):
    """{left: v, right: v with x mirrored}: the same limb direction on both sides."""
    v = np.asarray(v, float)
    return {"left": v, "right": v * np.array([-1.0, 1.0, 1.0])}


STAND = {"thigh": both(DOWN), "shank": both(DOWN), "upper": both(DOWN), "fore": both(DOWN)}
FLEX = np.radians(70.0)
ELBOW_FORWARD = {**STAND, "fore": both(-np.cos(FLEX) * Y + np.sin(FLEX) * Z)}
CROSS_LEGGED = {"thigh": both([np.sin(np.radians(40)), -0.05, np.cos(np.radians(40))]),
                "shank": both([-0.95, -0.1, -0.25]), "upper": both(DOWN), "fore": both(-0.5 * Y + 0.85 * Z)}


def clip(target, n_target=10, n_stand=5):
    """Standing frames first (every bone in the image plane, so lengths fit), then the target pose."""
    truth = np.stack([pose(**STAND)] * n_stand + [pose(**target)] * n_target)
    uv, conf = _observe(truth, noise_px=0.0)
    return truth, uv, conf


def test_ac_bp02_elbow_that_would_bend_backwards_gets_the_flexed_sign_in_a_photo():
    truth = pose(**ELBOW_FORWARD)[None]
    uv, conf = _observe(truth, noise_px=0.0)
    out = bp.BonesPrior().lift(uv, conf, K, SIZE)
    for side in ("left", "right"):
        el, wr = J[f"{side}_elbow"], J[f"{side}_wrist"]
        assert out[0, wr, 2] < out[0, el, 2] - 0.1, side  # the forearm points at the camera, as in truth
    r = rays(uv, K)
    lengths, depth, _ = fb.fit_lengths(r[..., :2], conf >= 0.5)
    pos, _ = fb.place(r, lengths, depth, bp.CONFIGS[None])
    terms = bp.limit_terms(pos, conf >= 0.5)
    assert terms["left_elbow"].max() > 60.0  # the mirrored root is a 70 degree hyperextension, so it costs


def test_ac_bp03_crossed_legs_seated_keep_knees_and_hips_in_limits():
    truth, uv, conf = clip(CROSS_LEGGED)
    out = bp.BonesPrior().lift(uv, conf, K, SIZE)
    terms = bp.limit_terms(out[:, None], conf >= 0.5)
    for name in ("left_knee", "right_knee", "left_hip_extension", "right_hip_extension"):
        assert terms[name][5:].max() < 1.0, name
    for side in ("left", "right"):  # knees nearer the camera than the hips, as in truth
        assert np.all(out[5:, J[f"{side}_knee"], 2] < out[5:, J[f"{side}_hip"], 2])
        assert np.all(truth[5:, J[f"{side}_knee"], 2] < truth[5:, J[f"{side}_hip"], 2])


def test_hinge_excess_counts_only_backward_bends():
    d = np.array([DOWN])
    axis = np.array([X])
    flexed = np.array([_unit(-np.cos(1.0) * Y - np.sin(1.0) * Z)])  # knee bends the shank back: flexion
    back = np.array([_unit(-np.cos(1.0) * Y + np.sin(1.0) * Z)])
    sideways = np.array([_unit(-np.cos(1.0) * Y + np.sin(1.0) * X)])
    assert bp.hinge_excess(d, flexed, axis)[0] == pytest.approx(0.0)
    assert bp.hinge_excess(d, back, axis)[0] == pytest.approx(np.degrees(1.0))
    assert bp.hinge_excess(d, sideways, axis)[0] == pytest.approx(0.0, abs=1e-9)
    assert bp.hinge_excess(d, d, axis)[0] == pytest.approx(0.0)  # straight: no sign


def test_arc_and_sagittal_excess():
    assert bp.arc_excess(-40.0, -30.0, 180.0) == pytest.approx(10.0)
    assert bp.arc_excess(-179.0, -30.0, 180.0) == pytest.approx(1.0)  # the short way round, past 180
    assert bp.arc_excess(-105.0, -30.0, 180.0) == pytest.approx(75.0)
    assert bp.arc_excess(90.0, -30.0, 180.0) == 0.0
    back40 = np.array([_unit(-np.cos(np.radians(40)) * Y - np.sin(np.radians(40)) * Z)])
    assert bp.sagittal_excess(back40, Y, Z, -bp.HIP_EXT, 180.0)[0] == pytest.approx(10.0)
    assert bp.sagittal_excess(np.array([X]), Y, Z, -bp.HIP_EXT, 180.0)[0] == pytest.approx(0.0)  # sideways


def test_trunk_twist_past_the_spine_limit_costs():
    straight = pose(**STAND)[None, None]
    twisted = straight.copy()
    mid = (twisted[..., J["left_shoulder"], :] + twisted[..., J["right_shoulder"], :]) / 2
    for name in ("left_shoulder", "right_shoulder"):  # turn the shoulder line 75 degrees about the camera y axis
        twisted[..., J[name], :] = mid + (twisted[..., J[name], :] - mid) @ _rot_y(np.radians(75)).T
    valid = np.ones((1, 17), bool)
    assert bp.limit_terms(straight, valid)["trunk_twist"][0, 0] == pytest.approx(0.0)
    assert bp.limit_terms(twisted, valid)["trunk_twist"][0, 0] == pytest.approx(75.0 - bp.SPINE_ROT, abs=0.5)


def test_ac_bp04_viterbi_keeps_a_sign_unless_its_joint_moves_little():
    unary = np.zeros((5, len(bp.CONFIGS)))
    unary[:, 1:] = 1.0
    unary[2, 1] = -0.5  # config 1 (one bit from config 0) wins frame 2 alone by 0.5
    gap = np.zeros((5, len(bp.CONFIGS), bp.CONFIGS.shape[1]))
    gap[..., -1] = 1.0  # the differing bit's joint jumps a full bone length on a flip
    np.testing.assert_array_equal(bp.viterbi(unary, gap), [0, 0, 0, 0, 0])
    gap[..., -1] = 0.1  # a bone near the image plane: flipping it is nearly free
    np.testing.assert_array_equal(bp.viterbi(unary, gap), [0, 0, 1, 0, 0])


def _reference_viterbi(unary, gap):
    """bones_prior.viterbi as it was before the forward pass could be fed in chunks (R8), copied here unchanged."""
    bits = bp.CONFIGS.astype(np.float32)
    v = unary[0].astype(np.float32)
    back = np.zeros(unary.shape, dtype=np.int32)
    prev = bp._flip_cost(bits, gap[0])
    for t in range(1, len(unary)):
        cur = bp._flip_cost(bits, gap[t])
        tot = v[:, None] + 0.5 * (prev + cur.T)
        back[t] = tot.argmin(axis=0)
        v = tot[back[t], np.arange(len(v))] + unary[t].astype(np.float32)
        prev = cur
    path = np.zeros(len(unary), dtype=np.int32)
    path[-1] = int(v.argmin())
    for t in range(len(unary) - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def _reference_solve(r, lengths, Z, valid):
    """bones_prior.solve as it was before R8, copied here unchanged: every chunk's jump costs kept in one
    (n, C, B) float64 array (about 82 KB per frame) until the whole clip's Viterbi ran."""
    chunks = [slice(i, i + fb.CHUNK) for i in range(0, len(r), fb.CHUNK)]
    unary, gaps = [], []
    for c in chunks:
        pos, _ = fb.place(r[c], lengths, Z[c], bp.CONFIGS[None])
        unary.append(bp.limit_excess(pos, valid[c]) / bp.DEG_UNIT + bp.W_WIDTH * bp.width_error(pos, lengths))
        gaps.append(bp.jumps(pos, r[c], lengths, Z[c]))
    unary, gaps = np.concatenate(unary), np.concatenate(gaps)
    path = _reference_viterbi(unary, bp.W_JUMP * gaps)
    return path, unary[np.arange(len(path)), path]


def _solve_inputs(n):
    """The arguments of solve for a noisy n-frame clip in which some joints are unconfident in some frames."""
    uv, conf = _observe(skeleton(n))
    conf[::7, [J["left_wrist"], J["right_knee"]]] = 0.1
    r = rays(uv, K)
    valid = conf >= fb.CONF_MIN
    lengths, Z, _ = fb.fit_lengths(r[..., :2], valid)
    return r, lengths, Z, valid


def _same_as_reference(n):
    args = _solve_inputs(n)
    path, prior = bp.solve(*args)
    want_path, want_prior = _reference_solve(*args)
    assert path.dtype == want_path.dtype and prior.dtype == want_prior.dtype
    assert np.array_equal(path, want_path) and np.array_equal(prior, want_prior)  # no tolerance: the same floats
    return path


def test_r8_the_chunked_forward_pass_equals_the_whole_clip_pass_bit_for_bit_on_200_frames():
    """Same operations on the same float32 and float64 values in the same order; only the jump costs of a finished
    chunk are dropped before the next chunk is made. So the path and the prior cost are identical (np.array_equal,
    not allclose: no summation order changed). 200 frames are six chunks and a partial one, on all 1024 configurations."""
    path = _same_as_reference(200)
    assert len(set(path.tolist())) > 1  # the clip makes the path move, so the comparison says something


@pytest.mark.parametrize("n", [1, 2, fb.CHUNK, fb.CHUNK + 1, 2 * fb.CHUNK + 1])
def test_r8_the_same_at_every_chunk_boundary(monkeypatch, n):
    """The chunk edge before, on and after the last frame, on every 16th configuration (the stitching does not depend
    on how many there are; the Viterbi of 1024 is what makes the 200-frame test slow)."""
    monkeypatch.setattr(bp, "CONFIGS", bp.CONFIGS[::16])
    _same_as_reference(n)


def test_r8_viterbi_over_the_whole_clip_is_the_same_as_over_chunks_of_it(monkeypatch):
    monkeypatch.setattr(bp, "CONFIGS", bp.CONFIGS[::16])
    rng = np.random.default_rng(5)
    unary = rng.random((70, len(bp.CONFIGS)))
    gap = rng.random((70, len(bp.CONFIGS), bp.CONFIGS.shape[1]))
    carry, pieces = None, []
    for i in range(0, 70, 25):  # runs of 25, 25 and 20 frames
        carry, back = bp.viterbi_forward(unary[i:i + 25], gap[i:i + 25], carry)
        pieces.append(back)
    assert np.array_equal(bp.backtrack(carry[0], np.concatenate(pieces)), bp.viterbi(unary, gap))
    assert np.array_equal(bp.viterbi(unary, gap), _reference_viterbi(unary, gap))


def test_r8_memory_grows_by_the_unary_row_and_the_back_pointers_per_frame_not_the_jump_costs(monkeypatch):
    """Peak traced memory for 64 and for 256 frames: the extra 192 frames add the unary row (8 KB) and the back
    pointers (4 KB) of each, about 12 KB a frame; the bound is 24 KB. The code before kept the jump costs of the whole
    clip (82 KB a frame, about 90 KB with the rest) and is over 60 KB, so the bounds tell the two apart. 64 frames
    are the smaller size because a clip of one chunk has one chunk's arrays alive, not two. The flip cost is stubbed
    (zeros): it is the same work for any length, and its 1024 x 1024 matmuls are what make this slow."""
    monkeypatch.setattr(bp, "_flip_cost", lambda bits, w: np.zeros((len(bits), len(bits)), np.float32))
    small, large = _solve_inputs(64), _solve_inputs(256)

    def per_frame(solve):
        def peak(args):
            tracemalloc.start()
            try:
                solve(*args)
                return tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()

        solve(*small)  # the first call allocates caches that are not the clip's
        return (peak(large) - peak(small)) / (256 - 64)

    assert per_frame(bp.solve) < 24_000
    assert per_frame(_reference_solve) > 60_000


def test_flip_cost_matches_its_definition():
    rng = np.random.default_rng(3)
    bits = bp.CONFIGS[:16].astype(np.float32)
    w = rng.random((16, bits.shape[1]))
    want = np.array([[w[i][bits[i] != bits[j]].sum() for j in range(16)] for i in range(16)])
    np.testing.assert_allclose(bp._flip_cost(bits, w), want, rtol=1e-5)


def test_jumps_are_the_gap_between_the_two_roots_over_the_length():
    uv, conf = _observe(skeleton(4), noise_px=0.0)
    r = lifters.rays(uv, K)
    lengths, Zr, _ = fb.fit_lengths(r[..., :2], conf >= 0.5)
    k = 1 + fb.CHAINS.index(("left_knee", "left_ankle"))
    near, _ = fb.place(r, lengths, Zr, np.zeros((1, 1, fb.N_BITS), np.int8))
    far, _ = fb.place(r, lengths, Zr, np.eye(fb.N_BITS, dtype=np.int8)[None, [k]])
    gap = bp.jumps(near, r, lengths, Zr)[:, 0, k]
    L = lengths[BODY_BONES.index(("left_knee", "left_ankle"))]
    moved = np.linalg.norm(far[:, 0, J["left_ankle"]] - near[:, 0, J["left_ankle"]], axis=-1)
    np.testing.assert_allclose(gap, moved / L, atol=1e-9)


def test_ac_bp04_moving_clip_signs_agree_with_truth_and_bones_stay_fixed():
    truth = skeleton(60)
    uv, conf = _observe(truth)
    out, info = bp.BonesPrior().lift_info(uv, conf, K, SIZE, 15.0)
    ok = total = 0
    for parent, child in fb.CHAINS[1:]:
        L = np.linalg.norm(truth[:, J[child]] - truth[:, J[parent]], axis=1)
        dz_true = truth[:, J[child], 2] - truth[:, J[parent], 2]
        dz_out = out[:, J[child], 2] - out[:, J[parent], 2]
        ok += int(np.sum((np.sign(dz_true) == np.sign(dz_out)) | (np.abs(dz_true) < 0.1 * L)))
        total += len(L)
    assert ok / total >= 0.95, ok / total
    assert bone_cv(out).mean() < 0.01 and info["bone_cv_mean"] < 0.01
    lengths = np.array(list(info["bone_lengths_m"].values()))
    got = np.median(bone_lengths(out), axis=0)
    fitted = [BODY_BONES.index(b) for b in (("right_shoulder", "right_hip"), ("left_shoulder", "right_shoulder"))]
    tree = [i for i in range(len(BODY_BONES)) if i not in fitted]  # every joint on its ray at its bone length
    np.testing.assert_allclose(got[tree], lengths[tree], rtol=1e-3)
    np.testing.assert_allclose(got[fitted], lengths[fitted], rtol=0.05)  # best fit to two lengths, as fixed-bones


def test_ac_bp05_scale_and_face_keep_every_joint_on_its_ray():
    uv, conf = _observe(skeleton(20), noise_px=1.0)
    out, info = bp.BonesPrior().lift_info(uv, conf, K, SIZE)
    np.testing.assert_allclose(project(out, K), uv, atol=1e-6)
    assert np.all(out[..., 2] > 0)
    ref = fb.FixedBones().lift_info(uv, conf, K, SIZE)[1]["bone_lengths_m"]
    for bone, length in info["bone_lengths_m"].items():
        assert length == pytest.approx(ref[bone] * bp.H_CHAIN / fb.H_REF, abs=2e-4)
    assert info["H_ref_m"] == bp.H_CHAIN


def test_ac_bp05_face_sits_ahead_of_the_shoulders_facing_the_camera_and_level_in_profile():
    for yaw, ahead in ((0.0, True), (90.0, False)):
        truth = np.stack([pose(**STAND, yaw_deg=yaw)] * 10)
        uv, conf = _observe(truth, noise_px=0.0)
        out = bp.BonesPrior().lift(uv, conf, K, SIZE)
        z_sh = (out[:, J["left_shoulder"], 2] + out[:, J["right_shoulder"], 2]) / 2
        nose = z_sh - out[:, J["nose"], 2]  # positive: nearer the camera than the shoulders
        k = bp.H_CHAIN / fb.H_REF
        if ahead:
            np.testing.assert_allclose(nose, bp.FACE_FWD["nose"] * k, atol=0.03)
        else:
            assert np.abs(nose).max() < 0.05


def test_ac_bp07_deterministic_and_shapes_refused():
    uv, conf = _observe(skeleton(12), noise_px=2.0)
    a, ia = bp.BonesPrior().lift_info(uv, conf, K, SIZE)
    b, ib = bp.BonesPrior().lift_info(uv, conf, K, SIZE)
    np.testing.assert_array_equal(a, b)
    assert ia == ib
    with pytest.raises(ValueError, match="bones-prior: expected kp2d"):
        bp.BonesPrior().lift(np.zeros((3, 16, 2)), np.ones((3, 16)), K)
    with pytest.raises(ValueError, match="expected kp2d"):
        bp.BonesPrior().lift(np.zeros((0, 17, 2)), np.ones((0, 17)), K)


def test_one_frame_photo_and_unconfident_joints():
    uv, conf = _observe(skeleton(1), noise_px=0.0)
    out, info = bp.BonesPrior().lift_info(uv, conf, K, SIZE)
    assert out.shape == (1, 17, 3) and np.isfinite(out).all() and info["sign_flips"] == 0
    uv, conf = _observe(skeleton(10), noise_px=0.0)
    conf[:, [J["left_wrist"], J["right_knee"]]] = 0.1
    out = bp.BonesPrior().lift(uv, conf, K, SIZE)
    assert np.isfinite(out).all()


def test_ac_bp01_the_registry_names_the_lifter_and_makes_it_the_default():
    assert lifters.names() == ["bones-prior", "fixed-bones", "motionbert"]
    assert lifters.resolve("bones-prior") == "bones-prior" and lifters.DEFAULT == "bones-prior"
    lift = lifters.get("bones-prior")
    assert isinstance(lift, bp.BonesPrior) and lift.available() == (True, "numpy only")
    assert lift.models() == [] and lift.licence_notes() == []
    assert stamp.entry_modules("cpu", lifter="bones-prior")[-1] == "part2.lifters.bones_prior"


def test_ac_bp01_the_module_loads_on_first_use_and_needs_only_numpy():
    code = ("import sys; from part2 import lifters; "
            "before = 'part2.lifters.bones_prior' in sys.modules; lifters.get('bones-prior'); "
            "print(before, 'part2.lifters.bones_prior' in sys.modules, "
            "any(m in sys.modules for m in ('torch', 'rtmlib', 'onnxruntime')))")
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert run.stdout.split() == ["False", "True", "False"]  # lazy like the others (AC-BP07); numpy only


def test_ac_bp06_cpu_backend_output_and_provenance(tmp_path):
    frames = _frames(tmp_path, 6)
    doc = cpu_rtm.Backend("bones-prior").estimate(frames, tmp_path / "body3d.json", model2d=Fake2D(6))
    assert doc["model"] == "rtmpose-x+bones-prior" and len(doc["frames"]) == 6
    p = doc["frames"][0]["people"][0]
    assert list(p["kp3d_cam"]) == list(p["kp2d"]) == CANONICAL and p["reproj_self_px"] < 0.05
    prov = doc["provenance"]
    assert prov["lifter"] == "bones-prior" and prov["backend"] == "cpu"
    assert [m["source"] for m in prov["models"]] == [cpu_rtm.DET["url"], cpu_rtm.POSE["url"]]
    info = prov["lifter_info"]["0"]
    fixed = fb.FixedBones().lift_info(Fake2D(6).kp, np.full((6, 17), 0.9), cpu_rtm.long_side_K(1280, 720))[1]
    assert set(fixed) - {"lifter"} <= set(info) and info["lifter"] == "bones-prior"
    assert {"sign_flips", "prior_cost_mean"} <= set(info)
    json.dumps(doc)  # serialisable as body3d.json
