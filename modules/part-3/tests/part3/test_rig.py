"""Part 4's rig: hierarchy, rest offsets, forward kinematics and fitting (AC-P01, TICKET-025)."""

import json

import numpy as np
import pytest

import part4rules as p4
from part3 import rig, standard
from part3.joints import JOINTS

PART4_HIERARCHY = {
    "left_hip": "pelvis", "right_hip": "pelvis", "neck": "pelvis",
    "left_knee": "left_hip", "left_ankle": "left_knee", "right_knee": "right_hip", "right_ankle": "right_knee",
    "left_shoulder": "neck", "right_shoulder": "neck", "nose": "neck",
    "left_elbow": "left_shoulder", "left_wrist": "left_elbow",
    "right_elbow": "right_shoulder", "right_wrist": "right_elbow",
    "left_eye": "nose", "right_eye": "nose", "left_ear": "left_eye", "right_ear": "right_eye",
}
PART4_FK_ORDER = (
    "left_hip", "left_knee", "left_ankle", "right_hip", "right_knee", "right_ankle", "neck",
    "left_shoulder", "left_elbow", "left_wrist", "right_shoulder", "right_elbow", "right_wrist",
    "nose", "left_eye", "left_ear", "right_eye", "right_ear",
)
SQRT_HALF = np.sqrt(0.5)


def standard_lengths(scale=1.0):
    return {bone: length * scale for bone, length in standard.bone_lengths().items()}


def asymmetric_lengths():
    """Left and right limbs differ; the pelvis and clavicle halves stay equal (the profile rule)."""
    lengths = standard_lengths()
    for bone in ("left_thigh", "left_upper_arm", "left_eye_link", "right_forearm", "right_ear_link"):
        lengths[bone] *= 1.17
    for bone in ("right_shank", "left_forearm", "right_eye_link"):
        lengths[bone] *= 0.86
    return lengths


PROFILES = {
    "simon-standard": standard_lengths(),
    "part4-rig-numbers": {**standard_lengths(), "left_thigh": 0.4165, "left_shank": 0.4182},
    "stature-1.85": standard_lengths(1.85 / 1.70),
    "child-0.9": standard_lengths(0.9 / 1.70),
    "asymmetric-limbs": asymmetric_lengths(),
}


def random_rotations(rng, max_deg=120.0):
    """A unit quaternion per rotated joint: random axis, angle uniform in [0, max_deg] degrees."""
    out = {}
    for joint in rig.ROTATED:
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        half = np.radians(rng.uniform(0.0, max_deg)) / 2
        out[joint] = [*(axis * np.sin(half)), np.cos(half)]
    return out


def as_arrays(joints):
    return np.array([joints[name] for name in JOINTS])


def max_gap(a, b):
    return max(float(np.linalg.norm(np.asarray(a[name]) - np.asarray(b[name]))) for name in JOINTS)


# --- hierarchy ---------------------------------------------------------------------------------

def test_hierarchy_is_exactly_part4s_rig():
    assert rig.HIERARCHY == PART4_HIERARCHY
    assert rig.FK_ORDER == PART4_FK_ORDER
    assert p4.PARENT == PART4_HIERARCHY and p4.FK_ORDER == PART4_FK_ORDER


def test_rotated_joints_are_the_19_with_pelvis_first_and_parents_precede_children():
    assert rig.ROTATED == ("pelvis",) + PART4_FK_ORDER and len(rig.ROTATED) == 19
    seen = {"pelvis"}
    for joint in rig.FK_ORDER:
        assert rig.HIERARCHY[joint] in seen
        seen.add(joint)


def test_kabsch_weights_are_the_canonical_joints_in_each_subtree():
    assert rig.WEIGHTS["left_hip"] == rig.WEIGHTS["right_hip"] == 3
    assert rig.WEIGHTS["neck"] == 11
    assert rig.WEIGHTS["left_shoulder"] == rig.WEIGHTS["right_shoulder"] == 3
    assert rig.WEIGHTS["nose"] == 5
    assert rig.WEIGHTS["left_eye"] == rig.WEIGHTS["right_eye"] == 2


# --- rest offsets ------------------------------------------------------------------------------

def test_rest_offsets_follow_the_spec_directions_and_profile_lengths():
    L = standard.bone_lengths()
    offsets = rig.rest_offsets(L)
    assert list(offsets) == list(rig.FK_ORDER)
    assert {j: e["parent"] for j, e in offsets.items()} == PART4_HIERARCHY
    expected = {
        "left_hip": [L["left_pelvis"], 0, 0], "right_hip": [-L["right_pelvis"], 0, 0],
        "left_knee": [0, -L["left_thigh"], 0], "right_knee": [0, -L["right_thigh"], 0],
        "left_ankle": [0, -L["left_shank"], 0], "right_ankle": [0, -L["right_shank"], 0],
        "neck": [0, L["spine"], 0],
        "left_shoulder": [L["left_clavicle"], 0, 0], "right_shoulder": [-L["right_clavicle"], 0, 0],
        "left_elbow": [L["left_upper_arm"], 0, 0], "right_elbow": [-L["right_upper_arm"], 0, 0],
        "left_wrist": [L["left_forearm"], 0, 0], "right_wrist": [-L["right_forearm"], 0, 0],
    }
    for joint, vector in expected.items():
        assert offsets[joint]["offset"] == pytest.approx(vector, abs=1e-12), joint


def test_the_arms_rest_in_a_t_pose_so_hanging_and_overhead_are_both_90_degrees_away():
    """Review B2: from a hanging rest an arm overhead is 180 degrees away (Part 4 rejects that turn)."""
    offsets = rig.rest_offsets(standard.bone_lengths())
    for side, sign in (("left", 1.0), ("right", -1.0)):
        for joint in ("elbow", "wrist"):
            rest = np.array(offsets[f"{side}_{joint}"]["offset"])
            direction = rest / np.linalg.norm(rest)
            assert direction == pytest.approx([sign, 0, 0], abs=1e-12)
            for target in ([0.0, -1.0, 0.0], [0.0, 1.0, 0.0]):  # hanging, overhead
                assert np.degrees(np.arccos(direction @ np.array(target))) == pytest.approx(90.0, abs=1e-9)


def test_head_offsets_point_as_the_neutral_head_at_the_profile_lengths():
    head = json.loads(standard.STANDARD_BODY_PATH.read_text())["neutral_head_m"]
    P = {name: np.array(v) for name, v in head.items()}
    lengths = {**standard_lengths(), "head": 0.2, "left_eye_link": 0.07, "right_ear_link": 0.09}
    offsets = rig.rest_offsets(lengths)
    links = {"nose": ("neck", "head"), "left_eye": ("nose", "left_eye_link"),
             "right_eye": ("nose", "right_eye_link"), "left_ear": ("left_eye", "left_ear_link"),
             "right_ear": ("right_eye", "right_ear_link")}
    for joint, (origin, bone) in links.items():
        vector = P[joint] - P[origin]
        want = vector / np.linalg.norm(vector) * lengths[bone]
        assert offsets[joint]["offset"] == pytest.approx(want, abs=1e-12), joint


def test_rest_offset_lengths_equal_the_bone_lengths_for_every_profile():
    pairs = {"left_hip": "left_pelvis", "right_hip": "right_pelvis", "left_knee": "left_thigh",
             "right_knee": "right_thigh", "left_ankle": "left_shank", "right_ankle": "right_shank",
             "neck": "spine", "left_shoulder": "left_clavicle", "right_shoulder": "right_clavicle",
             "left_elbow": "left_upper_arm", "right_elbow": "right_upper_arm", "left_wrist": "left_forearm",
             "right_wrist": "right_forearm", "nose": "head", "left_eye": "left_eye_link",
             "right_eye": "right_eye_link", "left_ear": "left_ear_link", "right_ear": "right_ear_link"}
    for lengths in PROFILES.values():
        offsets = rig.rest_offsets(lengths)
        for joint, bone in pairs.items():
            assert np.linalg.norm(offsets[joint]["offset"]) == pytest.approx(lengths[bone], abs=1e-12)


# --- forward kinematics: the convention --------------------------------------------------------

def test_forward_rest_pose_is_the_standing_body():
    offsets = rig.rest_offsets(standard.bone_lengths())
    identity = {j: [0, 0, 0, 1] for j in rig.ROTATED}
    posed = rig.forward(identity, offsets)
    assert posed["left_hip"] == pytest.approx([0.125, 0, 0])
    assert posed["right_hip"] == pytest.approx([-0.125, 0, 0])
    assert posed["left_ankle"] == pytest.approx([0.125, -(0.4165 + 0.4182), 0])
    assert posed["left_shoulder"] == pytest.approx([0.1979, 0.4896, 0])


def test_forward_hand_computed_composition_global_is_parent_times_local():
    """Pelvis 90 deg about z, left hip 90 deg about x: knee = hip + (0, 0, -thigh), not (thigh, 0, 0)."""
    L = standard.bone_lengths()
    offsets = rig.rest_offsets(L)
    rotations = {j: [0, 0, 0, 1] for j in rig.ROTATED}
    rotations["pelvis"] = [0, 0, SQRT_HALF, SQRT_HALF]
    rotations["left_hip"] = [SQRT_HALF, 0, 0, SQRT_HALF]
    posed = rig.forward(rotations, offsets)
    assert posed["left_hip"] == pytest.approx([0, L["left_pelvis"], 0], abs=1e-12)
    assert posed["right_hip"] == pytest.approx([0, -L["right_pelvis"], 0], abs=1e-12)
    assert posed["left_knee"] == pytest.approx([0, L["left_pelvis"], -L["left_thigh"]], abs=1e-12)
    assert posed["left_ankle"] == pytest.approx([0, L["left_pelvis"], -L["left_thigh"] - L["left_shank"]],
                                                abs=1e-12)
    assert posed["left_shoulder"] == pytest.approx([-L["spine"], L["left_clavicle"], 0], abs=1e-12)


def test_forward_quaternion_order_is_x_y_z_w():
    offsets = rig.rest_offsets(standard.bone_lengths())
    rotations = {j: [0, 0, 0, 1] for j in rig.ROTATED}
    rotations["pelvis"] = [0, 0, SQRT_HALF, SQRT_HALF]  # 90 degrees about z, w last
    posed = rig.forward(rotations, offsets)
    assert posed["left_hip"] == pytest.approx([0, 0.125, 0], abs=1e-12)


def test_forward_matches_the_independent_implementation_on_random_rotations():
    rng = np.random.default_rng(7)
    for lengths in PROFILES.values():
        offsets = rig.rest_offsets(lengths)
        for _ in range(20):
            rotations = random_rotations(rng)
            ours = rig.forward(rotations, offsets)
            theirs = p4.forward_kinematics(rotations, offsets)
            assert max_gap(ours, theirs) < 1e-9


def test_forward_ignores_quaternion_scale_and_subtracts_the_hip_midpoint():
    offsets = rig.rest_offsets(standard.bone_lengths())
    rotations = {j: [0, 0, 0, 2.0] for j in rig.ROTATED}
    posed = rig.forward(rotations, offsets)
    assert 0.5 * (posed["left_hip"] + posed["right_hip"]) == pytest.approx([0, 0, 0], abs=1e-12)


def test_forward_rejects_a_missing_or_zero_rotation_in_part4s_words():
    offsets = rig.rest_offsets(standard.bone_lengths())
    rotations = {j: [0, 0, 0, 1] for j in rig.ROTATED}
    without = {j: q for j, q in rotations.items() if j != "left_knee"}
    with pytest.raises(ValueError, match="missing a rotation for left_knee"):
        rig.forward(without, offsets)
    with pytest.raises(ValueError, match="right_elbow rotation is zero"):
        rig.forward({**rotations, "right_elbow": [0, 0, 0, 0]}, offsets)
    with pytest.raises(ValueError, match="left_wrist rotation must be a quaternion"):
        rig.forward({**rotations, "left_wrist": [0, 0, 1]}, offsets)


# --- quaternion helpers ------------------------------------------------------------------------

def test_matrix_and_quaternion_round_trip_including_half_turns():
    rng = np.random.default_rng(3)
    cases = [rng.normal(size=4) for _ in range(200)]
    cases += [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [SQRT_HALF, SQRT_HALF, 0, 0]]
    for raw in cases:
        q = rig.canonical_quat(raw)
        assert q[3] >= 0 and np.linalg.norm(q) == pytest.approx(1.0)
        again = rig.matrix_to_quat(rig.quat_to_matrix(q))
        assert again == pytest.approx(q, abs=1e-12)


def test_canonical_quaternion_has_w_non_negative_and_a_positive_first_part_at_a_half_turn():
    assert rig.canonical_quat([0, 0, 0, -1]) == pytest.approx([0, 0, 0, 1])
    assert list(rig.canonical_quat([0, -1, 0, 0])) == [0.0, 1.0, 0.0, 0.0]
    assert list(rig.canonical_quat([0, 0, -1, 0])) == [0.0, 0.0, 1.0, 0.0]


# --- AC-P01: round trip ------------------------------------------------------------------------

@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_p01_forward_fit_forward_round_trip_within_1e6_m_on_every_joint(profile):
    rng = np.random.default_rng(11)
    offsets = rig.rest_offsets(PROFILES[profile])
    for _ in range(40):
        pose = rig.forward(random_rotations(rng), offsets)
        rotations, fk, residual = rig.fit(pose, offsets)
        again = rig.forward(rotations, offsets)
        assert max_gap(again, pose) < 1e-6
        assert max_gap(fk, pose) < 1e-6
        assert max(residual.values()) < 1e-6


def test_p01_fit_takes_a_17x3_array_or_a_dict_with_the_same_result():
    rng = np.random.default_rng(5)
    offsets = rig.rest_offsets(standard.bone_lengths())
    pose = rig.forward(random_rotations(rng), offsets)
    from_dict = rig.fit({j: p.tolist() for j, p in pose.items()}, offsets)
    from_array = rig.fit(as_arrays(pose), offsets)
    from_xyz = rig.fit({j: {"x": p[0], "y": p[1], "z": p[2], "conf": 1.0} for j, p in pose.items()}, offsets)
    assert from_dict[0] == from_array[0] == from_xyz[0]
    with pytest.raises(ValueError, match="17"):
        rig.fit(np.zeros((16, 3)), offsets)


def test_fit_returns_unit_quaternions_with_w_non_negative_and_identity_at_the_leaves():
    rng = np.random.default_rng(9)
    offsets = rig.rest_offsets(standard.bone_lengths())
    pose = rig.forward(random_rotations(rng), offsets)
    rotations, _, residual = rig.fit(pose, offsets)
    assert list(rotations) == list(rig.ROTATED)
    for joint, q in rotations.items():
        assert q[3] >= 0 and np.linalg.norm(q) == pytest.approx(1.0), joint
    for leaf in ("left_ankle", "right_ankle", "left_wrist", "right_wrist", "left_ear", "right_ear"):
        assert rotations[leaf] == [0.0, 0.0, 0.0, 1.0]
    assert list(residual) == list(JOINTS)


def test_fit_of_the_rest_pose_is_the_identity_everywhere():
    offsets = rig.rest_offsets(standard.bone_lengths())
    rest = rig.forward({j: [0, 0, 0, 1] for j in rig.ROTATED}, offsets)
    rotations, _, _ = rig.fit(rest, offsets)
    for joint, q in rotations.items():
        assert q == pytest.approx([0, 0, 0, 1], abs=1e-12), joint


def test_fit_ignores_where_the_hip_midpoint_is():
    rng = np.random.default_rng(13)
    offsets = rig.rest_offsets(standard.bone_lengths())
    pose = as_arrays(rig.forward(random_rotations(rng), offsets))
    shifted = pose + np.array([0.31, -0.7, 2.2])
    a, b = rig.fit(pose, offsets), rig.fit(shifted, offsets)
    for joint in rig.ROTATED:
        assert a[0][joint] == pytest.approx(b[0][joint], abs=1e-12)
    assert max(b[2].values()) < 1e-9


# --- fit on poses the rig cannot reproduce -----------------------------------------------------

def test_fit_reports_the_residual_as_the_distance_to_the_target():
    offsets = rig.rest_offsets(standard.bone_lengths())
    rest = rig.forward({j: [0, 0, 0, 1] for j in rig.ROTATED}, offsets)
    pose = {j: p.copy() for j, p in rest.items()}
    pose["left_wrist"] = pose["left_wrist"] + np.array([0.1, 0.0, 0.0])  # forearm 0.1 m too long
    rotations, fk, residual = rig.fit(pose, offsets)
    assert residual["left_wrist"] == pytest.approx(0.1, abs=1e-12)
    assert sum(v for j, v in residual.items() if j != "left_wrist") < 1e-9
    assert float(np.linalg.norm(fk["left_wrist"] - pose["left_wrist"])) == pytest.approx(0.1, abs=1e-12)
    assert rig.residuals(fk, pose) == residual


def test_every_target_is_measured_from_the_fitted_parent_position():
    """A knee moved sideways drags the ankle target with the fitted knee: the ankle error stays its own."""
    offsets = rig.rest_offsets(standard.bone_lengths())
    rest = rig.forward({j: [0, 0, 0, 1] for j in rig.ROTATED}, offsets)
    pose = {j: p.copy() for j, p in rest.items()}
    pose["left_knee"] = pose["left_knee"] + np.array([0.05, 0.0, 0.0])
    _, fk, residual = rig.fit(pose, offsets)
    hip, knee = fk["left_hip"], fk["left_knee"]
    assert float(np.linalg.norm(knee - hip)) == pytest.approx(0.4165, abs=1e-12)  # the bone keeps its length
    direction = (pose["left_knee"] - hip) / np.linalg.norm(pose["left_knee"] - hip)
    assert (knee - hip) / 0.4165 == pytest.approx(direction, abs=1e-12)  # and points at the target
    ankle_goal = pose["left_ankle"] - knee
    assert float(np.linalg.norm(fk["left_ankle"] - knee)) == pytest.approx(0.4182, abs=1e-12)
    assert (fk["left_ankle"] - knee) / 0.4182 == pytest.approx(ankle_goal / np.linalg.norm(ankle_goal), abs=1e-12)
    assert residual["left_hip"] < 1e-12


def test_weighted_kabsch_is_the_least_squares_rotation_for_the_pelvis():
    offsets = rig.rest_offsets(standard.bone_lengths())
    rest = rig.forward({j: [0, 0, 0, 1] for j in rig.ROTATED}, offsets)
    rng = np.random.default_rng(17)
    pose = {j: p + rng.normal(scale=0.03, size=3) for j, p in rest.items()}
    rotations, _, _ = rig.fit(pose, offsets)
    centred = {j: p - 0.5 * (pose["left_hip"] + pose["right_hip"]) for j, p in pose.items()}
    goals = [centred["left_hip"], centred["right_hip"], 0.5 * (centred["left_shoulder"] + centred["right_shoulder"])]
    rests = [np.array(offsets[j]["offset"]) for j in ("left_hip", "right_hip", "neck")]
    weights = [3, 3, 11]

    def cost(q):
        R = rig.quat_to_matrix(q)
        return sum(w * np.sum((R @ a - b) ** 2) for w, a, b in zip(weights, rests, goals))

    best = cost(rotations["pelvis"])
    for _ in range(300):
        nearby = np.array(rotations["pelvis"]) + rng.normal(scale=0.02, size=4)
        assert cost(nearby) >= best - 1e-12


# --- antiparallel and degenerate targets -------------------------------------------------------

def test_antiparallel_shortest_arc_is_a_half_turn_about_a_fixed_perpendicular():
    """Elbow straight across the body from the shoulder: rest is +x, so 180 degrees; axis rest x e, e = y."""
    offsets = rig.rest_offsets(standard.bone_lengths())
    rest = rig.forward({j: [0, 0, 0, 1] for j in rig.ROTATED}, offsets)
    pose = {j: p.copy() for j, p in rest.items()}
    shoulder = rest["left_shoulder"]
    pose["left_elbow"] = shoulder + np.array([-0.3162, 0.0, 0.0])
    pose["left_wrist"] = shoulder + np.array([-(0.3162 + 0.2482), 0.0, 0.0])
    first, fk, _ = rig.fit(pose, offsets)
    second, _, _ = rig.fit(pose, offsets)
    assert first == second
    assert first["left_shoulder"] == pytest.approx([0.0, 0.0, 1.0, 0.0], abs=1e-12)
    assert fk["left_elbow"] == pytest.approx(pose["left_elbow"], abs=1e-12)


def test_antiparallel_in_a_rotated_parent_frame_still_reaches_the_target():
    rng = np.random.default_rng(21)
    offsets = rig.rest_offsets(standard.bone_lengths())
    rotations = random_rotations(rng)
    pose = rig.forward(rotations, offsets)
    glob = rig.quat_to_matrix(rotations["pelvis"]) @ rig.quat_to_matrix(rotations["neck"])
    shoulder = pose["left_shoulder"]
    # the elbow target is opposite to the rest direction as seen in the neck frame
    pose["left_elbow"] = shoulder - glob @ np.array([0.3162, 0.0, 0.0])
    _, fk, _ = rig.fit(pose, offsets)
    assert float(np.linalg.norm(fk["left_elbow"] - fk["left_shoulder"])) == pytest.approx(0.3162, abs=1e-12)
    assert (fk["left_elbow"] - fk["left_shoulder"]) == pytest.approx(pose["left_elbow"] - fk["left_shoulder"],
                                                                     abs=1e-9)


def test_a_target_on_top_of_its_parent_holds_the_rest_direction_without_nan():
    offsets = rig.rest_offsets(standard.bone_lengths())
    rest = rig.forward({j: [0, 0, 0, 1] for j in rig.ROTATED}, offsets)
    pose = {j: p.copy() for j, p in rest.items()}
    pose["left_knee"] = pose["left_hip"].copy()
    rotations, fk, residual = rig.fit(pose, offsets)
    assert all(np.isfinite(q).all() for q in rotations.values())
    assert all(np.isfinite(p).all() for p in fk.values())
    assert rotations["left_hip"] == pytest.approx([0, 0, 0, 1], abs=1e-12)
    everything_at_the_origin = rig.fit(np.zeros((17, 3)), offsets)
    assert all(np.isfinite(q).all() for q in everything_at_the_origin[0].values())
    assert np.isfinite(residual["left_knee"])


# --- twist continuity (stitching 2026-10-28, ASM-020) -------------------------------------------

def _bent_arm_pose(swing_deg, offsets):
    """Rest pose with the left upper arm overhead and the forearm folded 160 degrees back, its bend
    plane turned `swing_deg` about the upper arm: the seated stretch that broke the long-way rule."""
    joints = rig.forward({j: [0.0, 0.0, 0.0, 1.0] for j in rig.ROTATED}, offsets)
    shoulder = np.asarray(joints["left_shoulder"])
    upper = np.linalg.norm(offsets["left_elbow"]["offset"])
    fore = np.linalg.norm(offsets["left_wrist"]["offset"])
    elbow = shoulder + upper * np.array([0.0, 1.0, 0.0])
    s = np.radians(swing_deg)
    bend = np.array([np.cos(s), 0.0, np.sin(s)])
    fold = np.radians(160.0)
    direction = np.cos(fold) * np.array([0.0, 1.0, 0.0]) + np.sin(fold) * bend
    out = {name: np.asarray(p, dtype=float) for name, p in joints.items()}
    out["left_elbow"], out["left_wrist"] = elbow, elbow + fore * direction
    return {name: list(p) for name, p in out.items()}


def _keys(poses, offsets, continuity):
    keys, previous = [], None
    for index, pose in enumerate(poses):
        rotations, fk, _ = rig.fit(pose, offsets, previous if continuity else None)
        keys.append({"index": index * 10, "local_rotations": rotations, "fk": fk})
        previous = rotations
    return keys


def test_twist_continuity_keeps_a_folded_elbow_under_part4s_180_degree_step():
    offsets = rig.rest_offsets(standard_lengths())
    poses = [_bent_arm_pose(s, offsets) for s in (0, 80, 160, 80, 0)]
    # Part 4 takes the twist about the leaf bone out itself (TICKET-043), so even keys fitted without continuity
    # pass the guard; the old w >= 0 measure refused them. The continuity keys pass too.
    plain = _keys(poses, offsets, continuity=False)
    assert rig.long_way(plain, offsets) == [] == p4.long_way_steps(plain, offsets)
    keys = _keys(poses, offsets, continuity=True)
    assert rig.long_way(keys, offsets) == []
    for pose, key in zip(poses, keys):
        assert max_gap(key["fk"], pose) < 1e-9


def test_the_twist_moves_no_joint_and_the_first_key_matches_the_fit_without_previous():
    offsets = rig.rest_offsets(standard_lengths())
    rng = np.random.default_rng(7)
    rotations = random_rotations(rng)
    pose = {n: list(p) for n, p in rig.forward(rotations, offsets).items()}
    plain, fk_plain, _ = rig.fit(pose, offsets)
    _, fk_cont, _ = rig.fit(pose, offsets, previous=random_rotations(rng))
    assert max_gap(fk_plain, pose) < 1e-9 and max_gap(fk_cont, pose) < 1e-9
    assert rig.fit(pose, offsets, previous=None)[0] == plain


def test_no_gain_means_no_twist():
    """A straight limb at rest: every twist scores worse than none, so the rotation is the arc."""
    offsets = rig.rest_offsets(standard_lengths())
    pose = {n: list(p) for n, p in rig.forward({j: [0.0, 0.0, 0.0, 1.0] for j in rig.ROTATED},
                                               offsets).items()}
    rotations, _, _ = rig.fit(pose, offsets, previous={j: [0.0, 0.0, 0.0, 1.0] for j in rig.ROTATED})
    for joint in rig.TWIST_CHILD:
        assert np.allclose(rotations[joint], [0.0, 0.0, 0.0, 1.0], atol=1e-9)
