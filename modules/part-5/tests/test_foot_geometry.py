"""Foot geometry helpers (docs/specs/foot-keypoints.md AC-FOOT-01 to AC-FOOT-08, ADR-0015).

`_foot_rotation` and `_ankle_inversion` are pure maths on arrays of 3-vectors in the canonical frame (x subject-left,
y up, z anterior). Every expected value below is worked out by hand from the construction in the test, not read
back from the code. They are not in MEASURES or compute() (AC-FOOT-08): the foot measures have their own registry,
fed by Part 2's pose3d.json as an optional side input (TICKET-040, ADR-0015); the wiring is tested in test_feet.py.
"""
import math

import numpy as np
import pytest

from part5.measures import (MEASURES, MIN_CROSS_SHARE, MIN_GROUND_SHARE, MIN_TOE_SPREAD, _ankle_inversion,
                            _foot_rotation, compute, compute_feet)

HIP_L, HIP_R = (0.1, 0.0, 0.0), (-0.1, 0.0, 0.0)
ANKLE = (0.0, -0.82, 0.0)


def pt(*xyz):
    """One frame as a (1, 3) array."""
    return np.array([xyz], float)


def toe_at(heel, heading_deg, length=0.2):
    """A toe `length` from the heel in the ground plane, `heading_deg` from +z toward +x."""
    a = math.radians(heading_deg)
    return (heel[0] + length * math.sin(a), heel[1], heel[2] + length * math.cos(a))


def rot(hip_l=HIP_L, hip_r=HIP_R, heel=(0.1, -0.9, -0.1), toe=(0.1, -0.9, 0.1), side="left"):
    return float(_foot_rotation(pt(*hip_l), pt(*hip_r), pt(*heel), pt(*toe), side)[0])


def foot(side, roll=0.0, yaw=0.0):
    """Heel, big toe and small toe of one foot as (1, 3) arrays, 0.08 m below `ANKLE`.

    In the foot's own frame (forward, outer edge): heel (-0.08, 0), big toe (+0.12, -0.03, the inner edge),
    small toe (+0.09, +0.03). `roll` turns the sole toward the midline about the long axis (inversion: the outer edge
    goes down); `yaw` turns the whole foot about the vertical through the ankle, away from the midline.
    """
    sgn = 1.0 if side == "left" else -1.0
    c, s = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    out = []
    for fwd, lat in ((-0.08, 0.0), (0.12, -0.03), (0.09, 0.03)):
        # In the rolled foot a point is lat along the outer edge and 0.08 below the sole normal: (outward, up).
        outward, up = lat * c - 0.08 * s, -lat * s - 0.08 * c
        out.append(pt(ANKLE[0] + sgn * (outward * cy + fwd * sy), ANKLE[1] + up, ANKLE[2] + fwd * cy - outward * sy))
    return tuple(out)


def pitched(points, deg):
    """The foot points tilted `deg` about the lateral (x) axis through `ANKLE`, positive = toes up (heel down).

    Applied to a `foot()` with no yaw this is a roll about the foot's own long axis followed by a pitch.
    """
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    out = []
    for p in points:
        x, y, z = p[0][0], p[0][1] - ANKLE[1], p[0][2] - ANKLE[2]
        out.append(pt(x, ANKLE[1] + y * c + z * s, ANKLE[2] - y * s + z * c))
    return tuple(out)


def inversion(side, roll=0.0, yaw=0.0, pitch=0.0):
    heel, big, small = foot(side, roll, yaw)
    if pitch:
        heel, big, small = pitched((heel, big, small), pitch)
    return float(_ankle_inversion(heel, big, small, side)[0])


# --- _foot_rotation ----------------------------------------------------------------------------------------------

def test_foot_pointing_ahead_reads_zero_on_both_sides():
    """AC-FOOT-01. Heel to toe along +z against hips on the x axis: nothing across, 0.2 m ahead."""
    assert rot() == pytest.approx(0, abs=1e-9)
    assert rot(heel=(-0.1, -0.9, -0.1), toe=(-0.1, -0.9, 0.1), side="right") == pytest.approx(0, abs=1e-9)


def test_left_foot_turned_out_30_degrees_is_plus_30():
    """AC-FOOT-02. Foot vector 0.2 m long, 30 degrees toward +x: (0.2 sin30, 0, 0.2 cos30) = (0.1, 0, 0.173205);
    across 0.1, ahead 0.173205, atan2 = 30."""
    assert rot(toe=toe_at((0.1, -0.9, -0.1), 30)) == pytest.approx(30)


def test_right_foot_turned_out_30_degrees_is_plus_30():
    """AC-FOOT-02. Out for the right foot is toward -x, and it is still positive."""
    heel = (-0.1, -0.9, -0.1)
    assert rot(heel=heel, toe=toe_at(heel, -30), side="right") == pytest.approx(30)


def test_turned_in_is_negative_on_both_sides():
    """AC-FOOT-02. A toe pointing 20 degrees toward the midline: across -0.2 sin20 = -0.0684, ahead 0.2 cos20."""
    left = (0.1, -0.9, -0.1)
    right = (-0.1, -0.9, -0.1)
    assert rot(heel=left, toe=toe_at(left, -20)) == pytest.approx(-20)
    assert rot(heel=right, toe=toe_at(right, 20), side="right") == pytest.approx(-20)


def test_mirrored_pose_reads_the_same_on_the_other_side():
    """AC-FOOT-03. Negate x and swap left and right: the left reading becomes the right reading.
    Hand check: hip line (0.2, 0, 0.06), foot (0.09, 0.02, 0.19), across 0.1408, ahead 0.1561, atan2 = 42.05."""
    hip_l, hip_r, heel, toe = (0.1, 0.0, 0.03), (-0.1, 0.0, -0.03), (0.11, -0.9, -0.12), (0.2, -0.88, 0.07)

    def mirror(p):
        return (-p[0], p[1], p[2])

    left = rot(hip_l, hip_r, heel, toe, "left")
    right = rot(mirror(hip_r), mirror(hip_l), mirror(heel), mirror(toe), "right")
    assert left == pytest.approx(42.05, abs=0.01)
    assert right == pytest.approx(left)


def test_a_pelvis_that_turns_with_the_feet_reads_zero():
    """AC-FOOT-04. Hip line 40 degrees from +x toward +z, so the pelvis's forward is (-sin40, cos40) in (x, z).
    A foot along it reads 0 (across 0, ahead 0.2); a foot at world heading -25 degrees is 15 degrees further out
    than the pelvis's -40: across 0.2 sin(40-25), ahead 0.2 cos(40-25)."""
    a = math.radians(40)
    hip_l = (0.1 * math.cos(a), 0.0, 0.1 * math.sin(a))
    hip_r = (-hip_l[0], 0.0, -hip_l[2])
    heel = (0.0, -0.9, 0.0)
    assert rot(hip_l, hip_r, heel=heel, toe=toe_at(heel, -40)) == pytest.approx(0, abs=1e-9)
    assert rot(hip_l, hip_r, heel=heel, toe=toe_at(heel, -25)) == pytest.approx(15)


def test_height_does_not_change_the_heading():
    """AC-FOOT-04. A heel lifted 0.1 m: foot vector (0.05, 0.1, 0.1), heading atan2(0.05, 0.1) = 26.565 degrees."""
    assert rot(heel=(0.1, -0.8, -0.1), toe=(0.15, -0.9, 0.0)) == pytest.approx(math.degrees(math.atan2(0.05, 0.1)))


def test_a_series_is_measured_frame_by_frame_and_a_nan_frame_stays_nan():
    """AC-FOOT-05. Three frames: neutral, 45 degrees out, a NaN toe."""
    hip_l, hip_r = np.tile(HIP_L, (3, 1)), np.tile(HIP_R, (3, 1))
    heel = np.tile([0.1, -0.9, 0.0], (3, 1))
    toe = np.array([[0.1, -0.9, 0.2], [0.3, -0.9, 0.2], [np.nan, -0.9, 0.2]])
    r = _foot_rotation(hip_l, hip_r, heel, toe, "left")
    assert r[:2] == pytest.approx([0, 45])
    assert np.isnan(r[2])


@pytest.mark.parametrize("toe, why", [
    ((0.1, -0.9, 0.0), "zero length foot"),
    ((0.1, -0.7, 0.0), "foot standing on its toe, straight up"),
    ((0.12, -0.7, 0.02), "foot pitched 82 degrees: ground share 0.028 / 0.202 = 0.14 is under 0.25"),
    ((0.3, -0.9, 0.0), "foot sideways, 90 degrees from the pelvis's forward"),
    ((0.1, -0.9, -0.2), "toe behind the heel (heel and toe swapped)"),
    ((0.2, -0.9, -0.1), "foot 135 degrees from forward"),
])
def test_a_foot_with_no_usable_heading_is_nan(toe, why):
    """AC-FOOT-05. Heel at (0.1, -0.9, 0) in each case."""
    assert math.isnan(rot(heel=(0.1, -0.9, 0.0), toe=toe)), why


def test_just_inside_the_ground_guard_is_a_number():
    """AC-FOOT-05. Foot (0.05, 0.19, 0.05): length 0.2027, ground part 0.0707, share 0.35 >= 0.25; heading 45."""
    assert rot(heel=(0.1, -0.9, 0.0), toe=(0.15, -0.71, 0.05)) == pytest.approx(45)


def test_degenerate_hips_and_nan_input_are_nan():
    """AC-FOOT-05. Hips on one point, hips one above the other (no heading in the ground plane), a NaN hip."""
    assert math.isnan(rot(hip_l=(0, 0, 0), hip_r=(0, 0, 0)))
    assert math.isnan(rot(hip_l=(0, 0.1, 0), hip_r=(0, -0.1, 0)))
    assert math.isnan(rot(hip_l=(float("nan"), 0, 0)))


def test_the_guards_are_the_documented_values():
    """AC-FOOT-05. The spec names these three limits; a change to one is a change to the spec."""
    assert (MIN_GROUND_SHARE, MIN_CROSS_SHARE, MIN_TOE_SPREAD) == (0.25, 0.25, 0.1)


# --- _ankle_inversion --------------------------------------------------------------------------------------------
# The roll of the foot plane about its long axis against world up (0, 1, 0). Worked by hand for the flat foot of
# `foot()`: left heel (0, -0.9, -0.08), big toe (-0.03, -0.9, 0.12), small toe (0.03, -0.9, 0.09). The plane normal
# is (heel to big) x (heel to small) = (-0.03, 0, 0.2) x (0.03, 0, 0.17) = (0, 0.0111, 0), so up is +y. The long
# axis is toward the toe midpoint (0, 0, 0.105), +z, and the outer edge is up x axis = +x. World up has 1 along the
# foot's up and 0 along its outer edge, so the roll is atan2(-0, 1) = 0. Rolling the plane r degrees about +z (the
# outer edge going down) tilts the up to (sin r, cos r, 0) and the outer edge to (cos r, -sin r, 0): world up is then
# cos r along the up and -sin r along the outer edge, and the roll atan2(sin r, cos r) = r. The right foot is the
# mirror image.

@pytest.mark.parametrize("side", ["left", "right"])
def test_a_flat_foot_reads_zero(side):
    """AC-FOOT-06. The flat foot above: roll atan2(-0, 1) = 0, with no knee or shin in the call."""
    assert inversion(side) == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("side", ["left", "right"])
def test_a_sole_turned_toward_the_midline_is_positive(side):
    """AC-FOOT-06. The outer edge down by r reads +r (derivation above): 15 and 40 degrees, on both sides."""
    assert inversion(side, roll=15) == pytest.approx(15)
    assert inversion(side, roll=40) == pytest.approx(40)


@pytest.mark.parametrize("side", ["left", "right"])
def test_a_sole_turned_away_from_the_midline_is_negative(side):
    """AC-FOOT-06. The outer edge up by 10 degrees: world up is cos10 along the up and +sin10 along the outer
    edge, atan2(-sin10, cos10) = -10."""
    assert inversion(side, roll=-10) == pytest.approx(-10)
    assert inversion(side, roll=-35) == pytest.approx(-35)


def test_the_mirrored_foot_reads_the_same_on_the_other_side():
    """AC-FOOT-06. Negate x on the left foot rolled 20 degrees in: it is the right foot rolled 20 degrees in, and
    reads +20, not -20."""
    mirrored = tuple(pt(-p[0][0], p[0][1], p[0][2]) for p in foot("left", roll=20))
    for m, r in zip(mirrored, foot("right", roll=20)):
        assert m == pytest.approx(r)
    assert float(_ankle_inversion(*mirrored, "right")[0]) == pytest.approx(20)
    assert inversion("left", roll=20) == pytest.approx(20)


@pytest.mark.parametrize("side", ["left", "right"])
def test_the_foots_heading_does_not_change_the_roll(side):
    """AC-FOOT-07. A turn about the vertical keeps world up where it was: a foot turned out 30 degrees and rolled
    12 degrees in reads 12, and a flat one turned out reads 0."""
    assert inversion(side, roll=12, yaw=30) == pytest.approx(12)
    assert inversion(side, yaw=30) == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("side", ["left", "right"])
def test_a_raised_heel_or_a_lifted_toe_does_not_change_the_roll(side):
    """AC-FOOT-07. Roll r about the long axis, then a pitch p about the lateral axis: world up is cos(p)cos(r)
    along the foot's up and -cos(p)sin(r) along its outer edge, so the roll is atan2(sin r, cos r) = r for any p.
    A foot rolled 12 degrees in with the toes 30 up, or 30 down (heel raised), reads 12."""
    assert inversion(side, roll=12, pitch=30) == pytest.approx(12)
    assert inversion(side, roll=12, pitch=-30) == pytest.approx(12)
    assert inversion(side, pitch=-45) == pytest.approx(0, abs=1e-9)


def test_a_pitch_steep_enough_to_leave_a_quarter_of_world_up_across_the_foot_has_no_roll():
    """AC-FOOT-05. The share of world up across the long axis is cos(pitch): at 70 degrees 0.342 (a number, 12), at
    80 degrees 0.174, under MIN_CROSS_SHARE (0.25), and at 90 degrees 0 (standing on the toes): NaN."""
    assert inversion("left", roll=12, pitch=70) == pytest.approx(12)
    assert inversion("left", roll=12, pitch=-70) == pytest.approx(12)
    assert math.isnan(inversion("left", roll=12, pitch=80))
    assert math.isnan(inversion("left", roll=12, pitch=-80))
    assert math.isnan(inversion("left", pitch=90))


@pytest.mark.parametrize("side", ["left", "right"])
def test_a_foot_on_its_side_or_upside_down_is_nan(side):
    """AC-FOOT-05. World up is on the sole's side of the foot plane once the roll reaches 90 degrees: 80 reads 80,
    100 (cos100 < 0) and 180 are NaN."""
    assert inversion(side, roll=80) == pytest.approx(80)
    assert math.isnan(inversion(side, roll=100))
    assert math.isnan(inversion(side, roll=180))


@pytest.mark.parametrize("side", ["left", "right"])
def test_the_same_pose_turned_about_the_vertical_reads_the_same(side):
    """AC-FOOT-07. Heading is not part of a roll: turn every point 70 degrees about y and the 25 holds."""
    a = math.radians(70)

    def turn(p):
        x, y, z = p[0]
        return pt(x * math.cos(a) + z * math.sin(a), y, -x * math.sin(a) + z * math.cos(a))

    heel, big, small = foot(side, roll=25)
    before = float(_ankle_inversion(heel, big, small, side)[0])
    after = float(_ankle_inversion(turn(heel), turn(big), turn(small), side)[0])
    assert before == pytest.approx(25)
    assert after == pytest.approx(25)


def test_the_knee_and_ankle_are_not_read():
    """AC-FOOT-07. compute_feet gives the same roll whatever the shin does: a flat foot rolled 20 degrees in reads
    20 with the knee over the ankle, 0.4 m forward of it (a deep squat) and 0.1 m toward the midline (caving in)."""
    base = {"left_hip": pt(*HIP_L), "right_hip": pt(*HIP_R), "left_ankle": pt(*ANKLE)}
    for side in ("left", "right"):
        h, b, s = foot(side, roll=20)
        base.update({f"{side}_heel": h, f"{side}_big_toe": b, f"{side}_small_toe": s})
    reads = []
    for knee in ((0.0, -0.42, 0.0), (0.0, -0.42, 0.4), (-0.1, -0.42, 0.0), (float("nan"),) * 3):
        points = {**base, "left_knee": pt(*knee), "right_knee": pt(*knee), "right_ankle": pt(*ANKLE)}
        out = compute_feet(points)
        reads.append((float(out["left_ankle_inversion"][0]), float(out["right_ankle_inversion"][0])))
    assert reads == [pytest.approx((20, 20))] * 4


def test_a_series_of_frames_and_a_nan_frame():
    """AC-FOOT-05. Frames: 0 degrees, 20 degrees in, a NaN heel."""
    flat, rolled = foot("left"), foot("left", roll=20)
    nan_heel = pt(float("nan"), 0.0, 0.0)
    heel = np.vstack([flat[0], rolled[0], nan_heel])
    big, small = (np.vstack([flat[i], rolled[i], rolled[i]]) for i in (1, 2))
    r = _ankle_inversion(heel, big, small, "left")
    assert r[:2] == pytest.approx([0, 20])
    assert np.isnan(r[2])


def toes(sin_spread):
    """Heel and two toes 0.2 m from it, the left foot's big toe inner (-x), the angle between them asin(sin_spread)."""
    half = math.asin(sin_spread) / 2
    a, b = 0.2 * math.sin(half), 0.2 * math.cos(half)
    return pt(0, -0.9, 0), pt(-a, -0.9, b), pt(a, -0.9, b)


@pytest.mark.parametrize("sin_spread, finite", [(0.11, True), (0.09, False), (0.0, False)])
def test_toes_nearly_in_line_with_the_heel_have_no_foot_plane(sin_spread, finite):
    """AC-FOOT-05. sin of the angle at the heel: 0.11 is above MIN_TOE_SPREAD (0.1) and reads 0 for a flat foot;
    0.09 and 0 (collinear, cross product 0) are NaN."""
    heel, big, small = toes(sin_spread)
    r = float(_ankle_inversion(heel, big, small, "left")[0])
    assert math.isfinite(r) is finite
    if finite:
        assert r == pytest.approx(0, abs=1e-9)


def test_swapped_toes_are_nan_not_a_flipped_angle():
    """AC-FOOT-05. The big toe on the outer edge flips the plane normal; world up is then below the foot."""
    heel, big, small = foot("left", roll=10)
    assert math.isfinite(float(_ankle_inversion(heel, big, small, "left")[0]))
    assert math.isnan(float(_ankle_inversion(heel, small, big, "left")[0]))


def test_nan_input_is_nan():
    """AC-FOOT-05."""
    heel, big, small = foot("right", roll=10)
    assert math.isfinite(float(_ankle_inversion(heel, big, small, "right")[0]))
    for bad in range(3):
        pts = [heel, big, small]
        pts[bad] = pt(float("nan"), 0, 0)
        assert math.isnan(float(_ankle_inversion(*pts, "right")[0]))


def test_an_unknown_side_is_an_error():
    """AC-FOOT-05."""
    heel, big, small = foot("left")
    with pytest.raises(ValueError, match="side must be"):
        _ankle_inversion(heel, big, small, "center")
    with pytest.raises(ValueError, match="side must be"):
        _foot_rotation(pt(*HIP_L), pt(*HIP_R), pt(0, 0, 0), pt(0, 0, 0.2), "both")


def test_the_helpers_take_one_point_or_many():
    """AC-FOOT-05. A (3,) input is one frame, an (F, 3) input is F frames."""
    heel, toe = np.array([0.1, -0.9, 0.0]), np.array([0.2, -0.9, 0.2])
    one = _foot_rotation(np.array(HIP_L), np.array(HIP_R), heel, toe, "left")
    assert float(one) == pytest.approx(math.degrees(math.atan2(0.1, 0.2)))
    many = _foot_rotation(pt(*HIP_L), pt(*HIP_R), pt(0.1, -0.9, 0), pt(0.2, -0.9, 0.2), "left")
    assert many.shape == (1,)
    h, b, s = (p[0] for p in foot("left", roll=20))
    assert float(_ankle_inversion(h, b, s, "left")) == pytest.approx(20)
    assert _ankle_inversion(*foot("left", roll=20), "left").shape == (1,)


# --- a separate registry -------------------------------------------------------------------------------------------

def test_the_foot_geometry_is_not_part_of_the_body_registry():
    """AC-FOOT-08. The foot measures are wired in through their own registry (FOOT_MEASURES, fed from Part 2's
    pose3d.json, ADR-0015), so MEASURES and compute() hold the body measures only and a pair without a feet file
    is analysed exactly as before."""
    assert not any("foot_rotation" in n or "ankle_inversion" in n for n in MEASURES)
    with np.errstate(all="ignore"):
        assert set(compute(np.zeros((1, 17, 3)))) == set(MEASURES)
