"""Lifter B `fixed-bones` and the lifter registry (docs/specs/backends-gpu-cpu.md, AC-B07, edge cases)."""
import numpy as np
import pytest

from part2 import lifters
from part2.lifters import BODY_BONES, J, bone_cv, bone_lengths, place_root, project, rays
from part2.lifters import fixed_bones as fb

K = np.array([[1920.0, 0, 960], [0, 1920.0, 540], [0, 0, 1]])
SIZE = (1920, 1080)
YAW_T, YAW_DEG = [0.0, 0.2, 0.45, 0.6, 1.0], [-5.0, 5.0, 90.0, 90.0, -90.0]


def _rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _unit(v):
    return v / np.linalg.norm(v)


def skeleton(n=60, depth=4.0, seed=0):
    """A standing person swinging arms and legs who faces the camera for the first fifth of the clip, turns to
    profile, holds it, then turns through to the other profile (yaw knots YAW_T, YAW_DEG), in the OpenCV
    camera frame (x right, y down, z forward), so every bone is near-parallel to the image in at least a
    tenth of the frames (the assumption behind the 90th-percentile lengths). Bone lengths follow fb.RATIO, scaled so the
    standing chain (neck + torso + thigh + shin) is fb.H_REF, so absolute lengths are recoverable.
    Returns (n, 17, 3)."""
    unit = fb.H_REF / fb.RATIO[fb.CHAIN].sum()
    L = dict(zip(fb.SEGMENTS, fb.RATIO * unit))
    for a, b in fb.PAIRS:  # left and right equal, as the lifter assumes
        L[a] = L[b] = (L[a] + L[b]) / 2
    sw, hw = L[("left_shoulder", "right_shoulder")], L[("left_hip", "right_hip")]
    torso = L[("shoulder_mid", "hip_mid")]
    side = np.hypot(torso, (sw - hw) / 2)
    L[("left_shoulder", "left_hip")] = L[("right_shoulder", "right_hip")] = side
    t = np.linspace(0, 1, n)
    out = np.zeros((n, 17, 3))
    for i, ti in enumerate(t):
        x, y, z = np.eye(3)  # body axes: x left, y up, z front
        P = {"left_hip": hw / 2 * x, "right_hip": -hw / 2 * x,
             "left_shoulder": sw / 2 * x + torso * y, "right_shoulder": -sw / 2 * x + torso * y}
        neck = L[("nose", "shoulder_mid")]
        P["nose"] = torso * y + neck * _unit(0.85 * y + 0.5 * z)
        for side_name, sx in (("left", 1), ("right", -1)):
            P[f"{side_name}_eye"] = P["nose"] + 0.03 * sx * x + 0.03 * y - 0.02 * z
            P[f"{side_name}_ear"] = P["nose"] + 0.07 * sx * x + 0.01 * y - 0.09 * z
            ph = np.pi * (2 * ti + (0 if sx > 0 else 1))
            flex = np.radians(25 + 35 * np.sin(ph))  # shoulder flexion forward
            upper = _unit(-np.cos(flex) * y + np.sin(flex) * z)
            elbow = np.radians(40 + 30 * np.sin(ph + 1))  # elbow bends the forearm forward and up
            fore = _unit(-np.cos(flex + elbow) * y + np.sin(flex + elbow) * z)
            S = P[f"{side_name}_shoulder"]
            P[f"{side_name}_elbow"] = S + L[(f"{side_name}_shoulder", f"{side_name}_elbow")] * upper
            P[f"{side_name}_wrist"] = P[f"{side_name}_elbow"] + L[(f"{side_name}_elbow", f"{side_name}_wrist")] * fore
            hip_flex = np.radians(15 + 20 * np.sin(ph + 2))
            thigh = _unit(-np.cos(hip_flex) * y + np.sin(hip_flex) * z)
            knee = np.radians(25 + 20 * np.sin(ph + 2.5))  # knee bends the shank backwards
            shank = _unit(-np.cos(hip_flex - knee) * y + np.sin(hip_flex - knee) * z)
            H = P[f"{side_name}_hip"]
            P[f"{side_name}_knee"] = H + L[(f"{side_name}_hip", f"{side_name}_knee")] * thigh
            P[f"{side_name}_ankle"] = P[f"{side_name}_knee"] + L[(f"{side_name}_knee", f"{side_name}_ankle")] * shank
        body = np.array([P[name] for name in J])
        R = np.diag([1.0, -1.0, -1.0]) @ _rot_y(np.radians(np.interp(ti, YAW_T, YAW_DEG)))  # body (left, up, front) to camera
        out[i] = body @ R.T + np.array([0.2, 0.1, depth])
    return out


def _observe(kp3d, noise_px=2.0, seed=1):
    rng = np.random.default_rng(seed)
    uv = project(kp3d, K) + rng.normal(0, noise_px, kp3d.shape[:2] + (2,))
    return uv, np.ones(kp3d.shape[:2])


def test_ac_b07_recovers_lengths_depth_signs_and_stable_bones():
    truth = skeleton(60)
    uv, conf = _observe(truth)
    out, info = fb.FixedBones().lift_info(uv, conf, K, SIZE, 15.0)
    want = bone_lengths(truth).mean(axis=0)
    got = np.array(list(info["bone_lengths_m"].values()))
    assert np.all(np.abs(got / want - 1) <= 0.02), dict(zip(map(str, BODY_BONES), np.round(got / want, 3)))
    limbs = fb.CHAINS[1:]
    ok = total = 0
    for parent, child in limbs:
        L = np.linalg.norm(truth[:, J[child]] - truth[:, J[parent]], axis=1)
        dz_true = truth[:, J[child], 2] - truth[:, J[parent], 2]
        dz_out = out[:, J[child], 2] - out[:, J[parent], 2]
        # a near-parallel bone has both roots together: its sign carries no depth
        ok += int(np.sum((np.sign(dz_true) == np.sign(dz_out)) | (np.abs(dz_true) < 0.1 * L)))
        total += len(L)
    assert ok / total >= 0.95, ok / total
    assert bone_cv(out).mean() < 0.01 and info["bone_cv_mean"] < 0.01


def test_output_joints_lie_on_their_rays_so_reprojection_is_exact():
    uv, conf = _observe(skeleton(20))
    out = fb.FixedBones().lift(uv, conf, K, SIZE)
    np.testing.assert_allclose(project(out, K), uv, atol=1e-6)
    assert np.all(out[..., 2] > 0)


def test_forced_long_bone_is_clipped_and_counted():
    uv, conf = _observe(skeleton(30), noise_px=0.0)
    lw, le = J["left_wrist"], J["left_elbow"]
    uv[10, lw] = uv[10, le] + [600.0, 0.0]  # about 1.2 m from the elbow at 4 m: longer than any forearm
    lengths, Z, _ = fb.fit_lengths(rays(uv, K)[..., :2], conf >= fb.CONF_MIN)
    _, clipped = fb.place(rays(uv, K)[10:11], lengths, Z[10:11], fb.CONFIGS[None])
    assert (clipped >= 1).all()  # no configuration can reach the wrist ray
    out, info = fb.FixedBones().lift_info(uv, conf, K, SIZE)
    assert info["clipped"] >= 1
    np.testing.assert_allclose(project(out[10:11], K)[0, lw], uv[10, lw], atol=1e-6)  # closest point, on its ray


def test_one_frame_photo_uses_the_single_frame_for_lengths():
    uv, conf = _observe(skeleton(1), noise_px=0.0)
    out, info = fb.FixedBones().lift_info(uv, conf, K, SIZE)
    assert out.shape == (1, 17, 3) and np.isfinite(out).all()
    assert len(info["bone_lengths_m"]) == 12


def test_joint_never_confident_falls_back_to_its_partner():
    uv, conf = _observe(skeleton(40), noise_px=0.0)
    conf[:, J["right_ankle"]] = 0.2
    _, info = fb.FixedBones().lift_info(uv, conf, K, SIZE)
    lengths = info["bone_lengths_m"]
    assert lengths["right_knee-right_ankle"] == lengths["left_knee-left_ankle"]
    assert "right_knee-right_ankle" not in info["fallback_bones"]  # the partner was seen


def test_both_sides_never_confident_fall_back_to_the_ratio_table():
    uv, conf = _observe(skeleton(40), noise_px=0.0)
    conf[:, [J["left_wrist"], J["right_wrist"]]] = 0.1
    _, info = fb.FixedBones().lift_info(uv, conf, K, SIZE)
    assert {"left_elbow-left_wrist", "right_elbow-right_wrist"} <= set(info["fallback_bones"])
    ratio = fb.RATIO[fb.SEG[("left_elbow", "left_wrist")]] / fb.RATIO[fb.SEG[("left_shoulder", "left_elbow")]]
    lengths = info["bone_lengths_m"]
    assert lengths["left_elbow-left_wrist"] / lengths["left_shoulder-left_elbow"] == pytest.approx(ratio, rel=0.05)


def test_bone_seen_only_end_on_falls_back_instead_of_staying_short():
    lengths = np.array(fb.RATIO, dtype=float)
    n2d = np.tile(lengths, (5, 1))
    n2d[:, fb.SEG[("left_shoulder", "right_shoulder")]] *= 0.2  # shoulders overlap all clip (side view)
    got, fallback = fb._percentile_lengths(n2d, np.ones_like(n2d, bool), np.ones(5))
    assert "left_shoulder-right_shoulder" in fallback
    assert got[fb.SEG[("left_shoulder", "right_shoulder")]] == pytest.approx(fb.RATIO[0], rel=1e-6)


def test_scale_is_posture_invariant_through_the_standing_chain():
    uv, conf = _observe(skeleton(30), noise_px=0.0)
    info = fb.FixedBones().lift_info(uv, conf, K, SIZE)[1]
    L = info["bone_lengths_m"]
    assert L["left_hip-left_knee"] + L["left_knee-left_ankle"] < fb.H_REF


def test_bad_shapes_are_refused():
    with pytest.raises(ValueError, match="expected kp2d"):
        fb.FixedBones().lift(np.zeros((3, 16, 2)), np.ones((3, 16)), K)
    with pytest.raises(ValueError, match="expected kp2d"):
        fb.FixedBones().lift(np.zeros((0, 17, 2)), np.ones((0, 17)), K)


def test_median_filter_shrinks_its_window_at_the_ends():
    x = np.array([0.0, 10, 0, 0, 0, 9, 9])
    np.testing.assert_allclose(fb.median_filter(x, 5), [0, 0, 0, 0, 0, 4.5, 9])


def test_viterbi_prefers_fewer_flips_over_a_small_unary_gain():
    cost = np.zeros((3, len(fb.CONFIGS)))
    cost[[0, 2], 0] = -1.0
    cost[1, 1] = -0.5  # config 1 differs from config 0 by one bit; in and out costs 2
    np.testing.assert_array_equal(fb.viterbi(cost), [0, 0, 0])
    cost[1, 1] = -2.5
    np.testing.assert_array_equal(fb.viterbi(cost), [0, 1, 0])


def test_place_root_recovers_the_depth_of_a_known_pose():
    truth = skeleton(5, depth=6.0)
    uv, conf = _observe(truth, noise_px=0.0)
    rel = truth - lifters.hip_mid(truth)[:, None]
    placed = place_root(rel, uv, conf, K)
    np.testing.assert_allclose(placed, truth, atol=2e-3)


def test_rays_have_unit_depth_and_invert_projection():
    uv = np.array([[[960.0, 540.0], [1920.0, 0.0]]])
    r = rays(uv, K)
    np.testing.assert_allclose(r[..., 2], 1.0)
    np.testing.assert_allclose(project(r * 3.0, K), uv)


def test_registry_names_get_and_unknown():
    assert lifters.names() == ["fixed-bones", "motionbert"]
    assert lifters.get("fixed-bones").name == "fixed-bones"
    with pytest.raises(lifters.UnknownLifter) as e:
        lifters.get("x")
    assert str(e.value) == 'unknown lifter "x"; choose fixed-bones or motionbert'


def test_resolve_precedence_flag_then_env_then_default():
    assert lifters.resolve("motionbert", env={"PART2_LIFTER": "fixed-bones"}) == "motionbert"
    assert lifters.resolve(None, env={"PART2_LIFTER": "motionbert"}) == "motionbert"
    assert lifters.resolve(None, env={}) == lifters.DEFAULT
    with pytest.raises(lifters.UnknownLifter, match='"nope"'):
        lifters.resolve(None, env={"PART2_LIFTER": "nope"})


def test_body_bones_are_the_twelve_non_face_edges():
    assert len(BODY_BONES) == 12 and not any("eye" in a + b or "ear" in a + b or "nose" in a + b for a, b in BODY_BONES)


def test_bone_cv_is_zero_for_a_rigid_skeleton_and_positive_otherwise():
    pts = skeleton(10)
    rigid = np.repeat(pts[:1], 10, axis=0)
    assert bone_cv(rigid).max() == pytest.approx(0.0, abs=1e-12)
    assert bone_cv(pts * np.linspace(1, 1.5, 10)[:, None, None]).mean() > 0.1


def test_fixed_bones_has_no_models_or_licence_notes():
    b = fb.FixedBones()
    assert b.available() == (True, "numpy only") and b.models() == [] and b.licence_notes() == []
