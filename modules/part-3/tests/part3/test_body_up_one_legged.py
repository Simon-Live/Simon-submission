"""TICKET-038: body up from two-footed frames on one-legged exercises (part3/geometry.py body_up, ankle_gap).

Fixture: a synthetic upright body (no recorded data), 30 frames on both feet and 30 frames with the right leg
raised 45 degrees to the side with a straight knee, as in a standing leg abduction. Measured on it: the
previous rule (mean over every straight-knee frame) tilts up by about 6 degrees; the two-footed rule gives 0.
"""

import numpy as np
import pytest

from clipkit import doc_arrays, make_doc
from part3 import cli, contract, jsonschema_lite, geometry as g
from part3.views import part4 as part4_view
from part3.joints import INDEX, JOINTS

BASE = {
    "nose": (0.0, 1.62, 0.08), "left_eye": (0.03, 1.65, 0.07), "right_eye": (-0.03, 1.65, 0.07),
    "left_ear": (0.07, 1.63, 0.0), "right_ear": (-0.07, 1.63, 0.0),
    "left_shoulder": (0.18, 1.45, 0.0), "right_shoulder": (-0.18, 1.45, 0.0),
    "left_elbow": (0.2, 1.17, 0.0), "right_elbow": (-0.2, 1.17, 0.0),
    "left_wrist": (0.2, 0.92, 0.03), "right_wrist": (-0.2, 0.92, 0.03),
    "left_hip": (0.1, 0.9, 0.0), "right_hip": (-0.1, 0.9, 0.0),
    "left_knee": (0.1, 0.5, 0.01), "right_knee": (-0.1, 0.5, 0.01),
    "left_ankle": (0.1, 0.08, 0.0), "right_ankle": (-0.1, 0.08, 0.0),
}
TWO, RAISED, ABDUCTION_DEG = 30, 30, 45.0


def standing_body():
    return np.array([BASE[name] for name in JOINTS], dtype=float)


def abducted(body, deg):
    """The right leg turned `deg` degrees outward about the right hip (subject right is -x), knee straight."""
    out = body.copy()
    hip = out[INDEX["right_hip"]]
    R = g.rotation([0.0, 0.0, 1.0], -deg)
    for name in ("right_knee", "right_ankle"):
        out[INDEX[name]] = hip + R @ (out[INDEX[name]] - hip)
    return out


def leg_abduction_clip(turn=None):
    body = standing_body()
    J = np.stack([body] * TWO + [abducted(body, ABDUCTION_DEG)] * RAISED)
    return J if turn is None else J @ turn.T


def old_rule_up(J):
    """The rule before TICKET-038: mean feet-to-shoulders line over every straight-knee frame."""
    standing = np.all(g.knee_angles(J) > g.STANDING_KNEE_DEG, axis=-1)
    vec = g.point(J, "neck") - 0.5 * (g.point(J, "left_ankle") + g.point(J, "right_ankle"))
    return g.normalize(vec[standing].mean(axis=0))


def test_fixture_is_one_legged_with_straight_knees():
    J = leg_abduction_clip()
    assert np.all(g.knee_angles(J) > g.STANDING_KNEE_DEG)
    gap = g.ankle_gap(J, [0.0, 1.0, 0.0])
    assert np.all(gap[:TWO] == 0.0) and np.all(gap[TWO:] > g.RAISED_FOOT_GAP)


def test_one_legged_fixture_keeps_up_within_3_degrees_of_vertical():
    J = leg_abduction_clip()
    before = float(g.angle_between(old_rule_up(J), [0, 1, 0]))
    up, source = g.body_up(J)
    after = float(g.angle_between(up, [0, 1, 0]))
    assert before > 5.0, f"the fixture must show the bias: old rule tilt {before:.2f}"
    assert source == "two_footed_frames"
    assert after <= 3.0, f"tilt after {after:.2f} (before {before:.2f})"


def test_one_legged_fixture_under_a_tilted_camera_finds_the_turned_vertical():
    turn = g.rotation([1.0, 0.0, 0.3], 20.0)
    up, source = g.body_up(leg_abduction_clip(turn))
    assert source == "two_footed_frames"
    assert g.angle_between(up, turn @ np.array([0.0, 1.0, 0.0])) <= 3.0


def test_output_records_two_footed_frames_and_both_views_validate():
    J = leg_abduction_clip()
    out = cli.process(make_doc(J, np.ones(J.shape[:2])))
    assert out["frame"]["up_source"] == "two_footed_frames"
    assert jsonschema_lite.validate(out, contract.SCHEMAS["skeleton"]["schema"]) == []
    rendered = part4_view.render(out, keyframes="every:10")
    assert jsonschema_lite.validate(rendered, contract.SCHEMAS["skeleton-part4"]["schema"]) == []


def test_too_few_two_footed_frames_falls_back_to_the_standing_rule():
    body = standing_body()
    J = np.stack([body] * 4 + [abducted(body, ABDUCTION_DEG)] * RAISED)
    up, source = g.body_up(J)
    assert source == "standing_frames"
    assert np.array_equal(up, old_rule_up(J))


def test_small_raises_under_the_trigger_keep_the_old_rule():
    body = standing_body()
    J = np.stack([body] * TWO + [abducted(body, 20.0)] * RAISED)
    assert np.all(g.ankle_gap(J, [0.0, 1.0, 0.0])[TWO:] <= g.RAISED_FOOT_GAP)
    up, source = g.body_up(J)
    assert source == "standing_frames" and np.array_equal(up, old_rule_up(J))


@pytest.mark.parametrize("deg", [0.0, 25.0])
def test_two_footed_clips_are_unchanged(deg):
    J = np.stack([standing_body()] * 40) @ g.rotation([0.2, 0.1, 1.0], deg).T
    up, source = g.body_up(J)
    assert source == "standing_frames" and np.array_equal(up, old_rule_up(J))


def test_real_two_footed_squat_is_unchanged(real_doc):
    J = doc_arrays(real_doc)[0]
    up, source = g.body_up(J)
    assert source == "standing_frames" and np.array_equal(up, old_rule_up(J))


# The base commit (95d9888) gives exactly this up on the real Part 2 squat fixture (float.hex of each component).
BASE_REAL_UP = [float.fromhex("-0x1.dc9feee5d749ep-6"), float.fromhex("0x1.ff70f9fce6e6ep-1"),
                float.fromhex("-0x1.2b4e06c5103a0p-5")]


def test_real_squat_up_is_bit_identical_to_the_base_commit(real_doc):
    up, source = g.body_up(doc_arrays(real_doc)[0])
    assert source == "standing_frames" and up.tolist() == BASE_REAL_UP


def side_bend_clip(bend_deg):
    """Both feet down 0.4 m apart; the upper body bends sideways about the hip midpoint in half the frames."""
    body = standing_body()
    body[INDEX["left_ankle"]] = (0.2, 0.08, 0.0)
    body[INDEX["right_ankle"]] = (-0.2, 0.08, 0.0)
    body[INDEX["left_knee"]] = (0.15, 0.5, 0.01)
    body[INDEX["right_knee"]] = (-0.15, 0.5, 0.01)
    bent = body.copy()
    hip_mid = 0.5 * (body[INDEX["left_hip"]] + body[INDEX["right_hip"]])
    R = g.rotation([0.0, 0.0, 1.0], bend_deg)
    for name in JOINTS:
        if not name.endswith(("hip", "knee", "ankle")):
            bent[INDEX[name]] = hip_mid + R @ (body[INDEX[name]] - hip_mid)
    return np.stack([body] * 20 + [bent] * 20)


@pytest.mark.parametrize("bend", [20.0, 30.0, 45.0])
def test_side_bend_on_a_wide_stance_keeps_the_old_rule(bend):
    J = side_bend_clip(bend)
    assert np.all(g.knee_angles(J) > g.STANDING_KNEE_DEG)
    up, source = g.body_up(J)
    assert source == "standing_frames" and np.array_equal(up, old_rule_up(J))


def test_zero_trunk_frames_are_never_counted_as_two_footed():
    body = standing_body()
    raised = abducted(body, ABDUCTION_DEG)
    flat = raised.copy()
    for side in ("left", "right"):
        flat[INDEX[f"{side}_shoulder"]] = flat[INDEX[f"{side}_hip"]]
    J = np.stack([raised] * RAISED + [flat] * 5 + [body] * 4)
    up, source = g.body_up(J)
    assert source == "standing_frames" and np.array_equal(up, old_rule_up(J))


def test_one_missing_ankle_does_not_turn_the_rule_off():
    J = leg_abduction_clip()
    J[0, INDEX["left_ankle"]] = np.nan
    assert np.isfinite(g.ankle_gap(J, [0.0, 1.0, 0.0])[1:]).all()
    up, source = g.body_up(J)
    assert source == "two_footed_frames" and g.angle_between(up, [0, 1, 0]) <= 3.0


def test_ankle_gap_is_zero_for_legless_input_or_a_zero_direction():
    assert np.all(g.ankle_gap(np.zeros((3, 17, 3)), [0.0, 1.0, 0.0]) == 0.0)
    assert np.all(g.ankle_gap(leg_abduction_clip(), [0.0, 0.0, 0.0]) == 0.0)
