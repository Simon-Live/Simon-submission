"""The synthetic validation set (spec "Synthetic validation set"): layout, schedule, errors, geometry."""

import json
import math

import numpy as np
import pytest

from conftest import SYNTH_DIR
from part3 import bones, synth
from part3.angles import joints_array
from part3.geometry import angle_between, body_up, pelvis_frame, point
from part3.joints import GROUPS, INDEX, JOINTS, PAIRS, swap_index

OFFSETS = {1: 6, 2: 0, 3: 12, 4: 9}
MOTION = {1: 107, 2: 121, 3: 95, 4: 112}  # floor(106 / tempo) + 1
SWAPPED = {4: {**{i: "body" for i in range(20, 25)}, **{i: "body" for i in range(61, 66)}},
           3: {**{i: "legs" for i in range(30, 36)}, **{i: "legs" for i in range(80, 84)},
               **{i: "face" for i in range(86, 89)}},
           2: {i: "arms" for i in range(50, 54)}, 1: {}}
CAMERAS = {1: (0, 12, -5), 2: (45, -8, 6), 3: (90, 20, 3), 4: (180, -15, -8)}
LIMB = {"legs": ("knee", "ankle"), "arms": ("elbow", "wrist")}


def load(rel):
    return json.loads((SYNTH_DIR / rel).read_text())


@pytest.fixture(scope="module")
def sets():
    return {k: (load(f"take-{k}/pose3d.json"), load(f"take-{k}/truth.json")) for k in (1, 2, 3, 4)}


@pytest.fixture(scope="module")
def src():
    return synth.load_source()


def test_committed_layout_exists():
    expected = {"SOURCE.md", "take-1-mirrored/pose3d.json", "negative-armraise/pose3d.json",
                "negative-armraise/truth.json"}
    expected |= {f"take-{k}/{name}" for k in (1, 2, 3, 4) for name in ("pose3d.json", "truth.json")}
    found = {str(p.relative_to(SYNTH_DIR)) for p in SYNTH_DIR.rglob("*") if p.is_file()}
    assert found == expected


def test_source_md_says_synthetic_and_names_the_numbers():
    text = (SYNTH_DIR / "SOURCE.md").read_text()
    assert "synthetic" in text.lower()
    assert "433ae2edfe61b7e5c027f06ccdea289df34741225829f45fb5a652bb5147d857" in text
    assert "python3 -m part3.synth --out fixtures/input/synthetic-4take" in text
    assert "`flips_injected` = 27" in text


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_frame_count_is_offset_plus_tempo_frames(sets, k):
    doc, truth = sets[k]
    assert len(doc["frames"]) == OFFSETS[k] + MOTION[k] == len(truth["frames"])
    assert truth["start_offset_s"] == OFFSETS[k] / 15
    assert truth["take"] == k


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_pose3d_shape_numbering_and_rounding(sets, k):
    doc, _ = sets[k]
    assert list(doc) == ["frames"]  # only the mirrored file carries the extra key
    for i, frame in enumerate(doc["frames"]):
        assert frame["frame"] == i and frame["t_ms"] == round(1000 * i / 15, 3)
        (person,) = frame["people"]
        assert person["id"] == 0 and list(person["joints"]) == list(JOINTS)
    first = doc["frames"][0]["people"][0]["joints"]["nose"]
    assert all(round(first[a], 4) == first[a] for a in "xyz")
    assert "-0.0," not in json.dumps(doc)


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_camera_and_tempo_match_the_table(sets, k):
    truth = sets[k][1]
    az, pitch, roll = CAMERAS[k]
    assert truth["camera"] == {"azimuth_deg": az, "pitch_deg": pitch, "roll_deg": roll}
    assert truth["tempo"] == {1: 1.00, 2: 0.88, 3: 1.12, 4: 0.95}[k]


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_offset_frames_hold_truth_time_zero_then_time_advances(sets, k):
    t = np.array([f["truth_time_s"] for f in sets[k][1]["frames"]])
    assert (t[:OFFSETS[k]] == 0).all()
    assert (np.diff(t) >= -1e-9).all() and t.min() >= 0 and t.max() <= 106 / 15 + 1e-6


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_swaps_appear_exactly_where_scheduled(sets, k):
    swapped = {f["frame"]: f["swapped"] for f in sets[k][1]["frames"] if f["swapped"]}
    assert swapped == {i: [group] for i, group in SWAPPED[k].items()}


def test_twenty_seven_frames_are_injected(sets):
    assert sum(1 for k in sets for f in sets[k][1]["frames"] if f["swapped"]) == 27


def test_body_swap_turns_the_frame_a_half_turn(sets):
    # Part 2 builds x from the hip labels: a hip swap makes the face point to -z.
    doc, truth = sets[4]
    J = joints_array(doc)
    ahead = J[:, INDEX["nose"], 2] - 0.5 * (J[:, INDEX["left_ear"], 2] + J[:, INDEX["right_ear"], 2])
    swapped = np.array([bool(f["swapped"]) for f in truth["frames"]])
    assert (ahead[~swapped] > 0).all() and (ahead[swapped] < 0).all()


def test_left_hip_is_always_at_positive_x(sets):
    for k in sets:
        J = joints_array(sets[k][0])
        assert (J[:, INDEX["left_hip"], 0] > 0).all()


def expected_canonical(k, truth):
    """The clean truth of take k in Part 2's frame for that take's camera (before errors and swaps)."""
    clean = np.array([[f["joints"][name] for name in JOINTS] for f in truth["frames"]])
    return pelvis_frame(clean, synth.camera_axes(*CAMERAS[k])[2])[0]


@pytest.mark.parametrize("k, group", [(3, "legs"), (2, "arms")])
def test_limb_swap_exchanges_the_labelled_sides_exactly_when_scheduled(sets, k, group):
    doc, truth = sets[k]
    J, expected = joints_array(doc), expected_canonical(k, truth)
    left, right = [INDEX[f"left_{part}"] for part in LIMB[group]], [INDEX[f"right_{part}"] for part in LIMB[group]]
    same = np.linalg.norm(J[:, left] - expected[:, left], axis=2).sum(axis=1)
    cross = np.linalg.norm(J[:, left] - expected[:, right], axis=2).sum(axis=1)
    flagged = np.array([group in f["swapped"] for f in truth["frames"]])
    assert flagged.sum() > 0
    assert (cross[flagged] < same[flagged]).all() and (same[~flagged] < cross[~flagged]).all()


def test_take_three_far_side_joints_are_low_confidence_everywhere_else_full(sets):
    far = ("right_elbow", "right_wrist", "right_knee", "right_ankle")
    for k in sets:
        for frame, truth in zip(sets[k][0]["frames"], sets[k][1]["frames"]):
            expected = {name: 0.3 if k == 3 and name in far else 1.0 for name in JOINTS}
            for group in truth["swapped"]:  # conf travels with the position
                for left, right in GROUPS[group]:
                    expected[left], expected[right] = expected[right], expected[left]
            assert {n: j["conf"] for n, j in frame["people"][0]["joints"].items()} == expected
    assert sum(j["conf"] == 0.3 for f in sets[3][0]["frames"] for j in f["people"][0]["joints"].values()) == 4 * 107


def test_mirrored_file_is_flagged_and_undoes_to_take_one():
    mirrored, take1 = load("take-1-mirrored/pose3d.json"), load("take-1/pose3d.json")
    assert mirrored["mirrored"] is True and "mirrored" not in take1
    undone = joints_array(mirrored)[:, swap_index(PAIRS)] * np.array([-1.0, 1.0, 1.0])
    assert np.abs(undone - joints_array(take1)).max() < 1e-4
    assert [f["t_ms"] for f in mirrored["frames"]] == [f["t_ms"] for f in take1["frames"]]


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_up_in_input_is_a_unit_vector(sets, k):
    ups = np.array([f["up_in_input"] for f in sets[k][1]["frames"]])
    assert np.allclose(np.linalg.norm(ups, axis=1), 1.0, atol=1e-5)


def test_body_swapped_frames_carry_the_half_turn_in_up_in_input(sets):
    truth = sets[4][1]
    ups = np.array([f["up_in_input"] for f in truth["frames"]])
    swapped = np.array([bool(f["swapped"]) for f in truth["frames"]])
    # x and z flip under a half turn about y, y stays
    ref = ups[~swapped].mean(axis=0)
    assert np.allclose(ups[swapped].mean(axis=0) * [-1, 1, -1], ref, atol=0.05)


def test_up_in_input_is_the_true_up_seen_by_the_camera_tilt(sets):
    # The pitch/roll show up as the tilt of up_in_input away from +y (the camera's up) in that take.
    for k, (_, truth) in sets.items():
        ups = np.array([f["up_in_input"] for f in truth["frames"] if "body" not in f["swapped"]])
        tilt = float(angle_between(ups.mean(axis=0), np.array([0.0, 1.0, 0.0])))
        _, pitch, roll = CAMERAS[k]
        assert abs(tilt - math.hypot(pitch, roll)) < 4.0  # plus the 2.7 degree true-up offset at most


def test_clean_truth_has_constant_bone_lengths_and_the_fixture_medians(sets, src):
    for k in sets:
        truth = np.array([[f["joints"][name] for name in JOINTS] for f in sets[k][1]["frames"]])
        L = bones.measure(truth)
        assert np.abs(L - src.lengths).max() < 6e-4  # 4-decimal rounding only


def test_noise_sigma_matches_the_spec_description(src):
    hips = [INDEX["left_hip"], INDEX["right_hip"]]
    assert (src.sigma[hips] < 0.001).all()
    others = np.delete(src.sigma, hips)
    assert (others > 0.003).all() and (others < 0.012).all()


def test_source_frames_are_rigid_and_smoothed(src):
    assert np.abs(bones.measure(src.frames) - src.lengths).max() < 1e-9
    assert len(src.frames) == 107 and math.isclose(src.duration, 106 / 15)


def test_camera_axes_orthonormal_and_azimuth_conventions():
    f, r, u = synth.camera_axes(0, 0, 0)
    assert np.allclose(f, [0, 0, -1]) and np.allclose(r, [1, 0, 0]) and np.allclose(u, [0, 1, 0])
    f, r, u = synth.camera_axes(90, 0, 0)  # camera on the subject's left (+x), looking along -x
    assert np.allclose(f, [-1, 0, 0]) and np.allclose(u, [0, 1, 0])
    f, r, u = synth.camera_axes(180, 0, 0)
    assert np.allclose(f, [0, 0, 1]) and np.allclose(r, [-1, 0, 0])
    for az, pitch, roll in CAMERAS.values():
        f, r, u = synth.camera_axes(az, pitch, roll)
        basis = np.stack([r, u, -f])
        assert np.allclose(basis @ basis.T, np.eye(3)) and np.linalg.det(basis) > 0
        assert math.isclose(float(angle_between(u, np.array([0.0, 1.0, 0.0]))), math.hypot(pitch, roll), abs_tol=2.0)


def test_pitch_tilts_the_optical_axis_up():
    f, _, _ = synth.camera_axes(0, 20, 0)
    assert f[1] > 0 and math.isclose(math.degrees(math.asin(f[1])), 20.0, abs_tol=1e-9)


def test_draw_order_is_fixed():
    phi, amp, psi, bias, factors, noise = synth.draw(1, 5)
    rng = np.random.default_rng([20261027, 1])
    assert phi == rng.uniform(0, 2 * np.pi)
    pairs = rng.uniform(size=(8, 2))
    assert np.allclose(amp, 1.5 * pairs[:, 0]) and np.allclose(psi, 2 * np.pi * pairs[:, 1])
    assert bias == rng.uniform(-0.1, 0.1)
    assert np.array_equal(factors, rng.normal(1.0, 0.03, size=(5, 18)))
    assert np.array_equal(noise, rng.standard_normal((5, 17, 3)))
    again = synth.draw(1, 5)
    assert again[0] == phi and np.array_equal(again[5], noise)


def test_depth_bias_moves_joints_only_along_the_optical_axis(src):
    f = np.array([0.0, 0.0, -1.0])
    clean = src.frames[:4]
    J, conf = synth.corrupt(src, clean, f, 0.1, np.ones((4, 18)), np.zeros((4, 17, 3)), far_side=False)
    moved = J - clean
    assert np.abs(moved[..., :2]).max() < 1e-9 and np.abs(moved[..., 2]).max() > 0.01
    assert (conf == 1.0).all()


def test_performance_variation_is_small_and_keeps_bone_lengths(src):
    amp, psi = np.full(8, 1.5), np.zeros(8)
    times = np.linspace(0, src.duration, 12)
    J = synth.apply_variation(src.frames[:12], times, src.duration, amp, psi)
    assert np.abs(bones.measure(J) - bones.measure(src.frames[:12])).max() < 1e-9
    thigh_before = src.frames[:12, INDEX["left_knee"]] - src.frames[:12, INDEX["left_hip"]]
    thigh_after = J[:, INDEX["left_knee"]] - J[:, INDEX["left_hip"]]
    assert np.max(angle_between(thigh_before, thigh_after)) <= 1.5 + 1e-6
    shank_before = src.frames[:12, INDEX["left_ankle"]] - src.frames[:12, INDEX["left_knee"]]
    shank_after = J[:, INDEX["left_ankle"]] - J[:, INDEX["left_knee"]]
    assert np.max(angle_between(shank_before, shank_after)) <= 3.0 + 1e-6


def test_reflection_keeps_the_hip_midpoint_and_bone_lengths(src):
    r = np.array([0.6, 0.0, 0.8])
    J = src.frames[:6]
    M = synth.reflect(J, r)
    assert np.allclose(point(M, "root"), point(J, "root"))
    assert np.abs(bones.measure(M) - bones.measure(J)).max() < 1e-9
    assert np.allclose(synth.reflect(M, r), J)


def test_swap_injection_moves_conf_with_the_position():
    J = np.arange(2 * 17 * 3, dtype=float).reshape(2, 17, 3)
    conf = np.ones((2, 17))
    conf[:, INDEX["right_knee"]] = 0.3
    out, out_conf, swapped = synth.inject_swaps(J, conf, (("legs", 1, 1),))
    assert swapped == [[], ["legs"]]
    assert np.allclose(out[1, INDEX["left_knee"]], J[1, INDEX["right_knee"]])
    assert out_conf[1, INDEX["left_knee"]] == 0.3 and out_conf[1, INDEX["right_knee"]] == 1.0
    assert np.array_equal(out[0], J[0]) and np.array_equal(out[1, INDEX["nose"]], J[1, INDEX["nose"]])


def test_armraise_set(src):
    doc, truth = load("negative-armraise/pose3d.json"), load("negative-armraise/truth.json")
    assert len(doc["frames"]) == len(truth["frames"]) == 105 and truth["tempo"] == 1.0
    assert truth["camera"] == {"azimuth_deg": 180, "pitch_deg": -15, "roll_deg": -8}
    assert all(f["swapped"] == [] for f in truth["frames"]) and truth["start_offset_s"] == 0.0
    J = np.array([[f["joints"][name] for name in JOINTS] for f in truth["frames"]])
    legs = [INDEX[n] for n in ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")]
    assert np.abs(J[:, legs] - J[0, legs]).max() < 1e-9  # legs and trunk fixed
    abduction = lambda i, side: float(angle_between(  # noqa: E731
        J[i, INDEX[f"{side}_wrist"]] - J[i, INDEX[f"{side}_shoulder"]], np.array([0.0, -1.0, 0.0])))
    assert abduction(0, "left") < 1e-6 and abduction(0, "right") < 1e-6
    assert math.isclose(abduction(26, "left"), 85 * (1 - math.cos(2 * math.pi * 26 / 15 / 3.5)), abs_tol=1e-2)
    assert J[13, INDEX["left_wrist"], 0] > J[13, INDEX["left_shoulder"], 0]   # left arm towards +x
    assert J[13, INDEX["right_wrist"], 0] < J[13, INDEX["right_shoulder"], 0]  # right arm towards -x
    arm = np.linalg.norm(J[:, INDEX["left_wrist"]] - J[:, INDEX["left_shoulder"]], axis=1)
    assert np.allclose(arm, arm[0], atol=2e-4)  # upper arm and forearm collinear at truth lengths
    assert body_up(J)[1] == "all_frames"
