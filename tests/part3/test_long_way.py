"""Part 4's long-way rule as `part3.rig.long_way` applies it (spec integration-contract.md AC-P02, review B2)."""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

from part3 import doctor, rig
from part3.schema import ContractError, LongWayError
from part3.views import part4

import part4rules


def _quat_about_z(deg):
    half = math.radians(deg) / 2.0
    return [0.0, 0.0, math.sin(half), math.cos(half)]


def _keys(angles_by_index, joint="left_shoulder"):
    keys = []
    for index, deg in angles_by_index:
        rotations = {name: [0.0, 0.0, 0.0, 1.0] for name in rig.ROTATED}
        rotations[joint] = _quat_about_z(deg)
        keys.append({"index": index, "local_rotations": rotations})
    return keys


def _quat_about(axis, deg):
    half = math.radians(deg) / 2.0
    return [*(math.sin(half) * c for c in axis), math.cos(half)]


def _two_axis_keys():
    """170 degrees about x, then 170 about z in one gap: the case Part 4's README says takes the long way."""
    keys = _keys([(0, 0.0), (10, 0.0)])
    keys[0]["local_rotations"]["left_shoulder"] = _quat_about([1, 0, 0], 170.0)
    keys[1]["local_rotations"]["left_shoulder"] = _quat_about([0, 0, 1], 170.0)
    return keys


def test_ac_p02_small_steps_pass():
    assert rig.long_way(_keys([(0, 0.0), (10, 60.0), (20, 120.0), (30, 170.0)])) == []


def test_ac_p02_two_large_turns_about_different_axes_in_one_gap_are_the_long_way():
    steps = rig.long_way(_two_axis_keys())
    assert len(steps) == 1
    step = steps[0]
    assert step["joint"] == "left_shoulder" and (step["from_index"], step["to_index"]) == (0, 10)
    assert step["deg"] > 180.0


def test_ticket_042_a_joint_passing_180_degrees_is_a_small_step_not_a_wrap():
    """Shoulder 180.0 to 168.9 degrees on staging job 38c0651eaa90 (keys 200 and 205): 14.5 degrees apart."""
    for start, stop in ((170.0, 190.0), (179.0, 181.0), (180.0, 168.9), (175.0, 200.0)):
        for flip in (False, True):
            keys = _keys([(0, start), (5, stop)])
            if flip:  # the file writes w >= 0, so the second key may be the opposite sign
                keys[1]["local_rotations"]["left_shoulder"] = [-c for c in keys[1]["local_rotations"]["left_shoulder"]]
            assert rig.long_way(keys) == [], (start, stop, flip)


def test_ticket_042_the_w_zero_boundary_with_a_tilted_axis_does_not_flip_the_rotation_vector():
    axis = np.array([0.757857, 0.110874, 0.64293])
    axis /= np.linalg.norm(axis)
    keys = _keys([(0, 0.0), (200, 0.0), (205, 0.0)])
    keys[1]["local_rotations"]["left_shoulder"] = _quat_about(axis, 180.5)
    keys[2]["local_rotations"]["left_shoulder"] = _quat_about(axis, 168.9)
    keys[2]["local_rotations"]["left_shoulder"] = [-c for c in keys[2]["local_rotations"]["left_shoulder"]]
    assert rig.long_way(keys) == []
    assert part4rules.long_way_steps(keys) == []


def test_rotation_vector_wrapped_form_stays_0_to_180_degrees_for_any_rotation():
    for deg in (0.0, 45.0, 179.0, 181.0, 300.0):
        v = rig.rotation_vector(_quat_about_z(deg))
        assert 0.0 <= math.degrees(np.linalg.norm(v)) <= 180.0 + 1e-9


def test_ac_p02_a_negated_quaternion_is_the_same_key():
    keys = _keys([(0, 30.0), (10, 40.0)])
    keys[1]["local_rotations"]["left_shoulder"] = [-c for c in keys[1]["local_rotations"]["left_shoulder"]]
    assert rig.long_way(keys) == []


def test_the_part4_views_refusal_is_a_long_way_error_with_the_step_as_attributes():
    keys = _two_axis_keys()
    with pytest.raises(LongWayError) as caught:
        part4._check_long_way(keys)
    error = caught.value
    assert isinstance(error, ContractError)
    assert (error.path, error.joint, error.from_index, error.to_index, error.limit_deg) == (
        "--view part4", "left_shoulder", 0, 10, 180.0)
    assert error.degrees == rig.long_way(keys)[0]["deg"] > 180.0
    assert str(error) == (f"--view part4: Part 4 would reject this clip: left_shoulder turns {error.degrees} degrees "
                          "between keys 0 and 10 (Part 4 allows 180); add keys between them (a smaller every:<n>) "
                          "or use another view")


def test_r9_the_view_and_doctor_share_one_long_way_next_step():
    assert rig.LONG_WAY_FIX == "add keys between them (a smaller every:<n>) or use another view"
    assert doctor.FIX_LONG_WAY is rig.LONG_WAY_FIX
    with pytest.raises(LongWayError) as caught:
        part4._check_long_way(_two_axis_keys())
    assert caught.value.msg.endswith(f"; {rig.LONG_WAY_FIX}")


# --- TICKET-043: the guard runs the two steps Part 4 runs before it measures ------------------------

def test_rotation_vector_unwrapped_runs_0_to_360_degrees_and_keeps_the_sign():
    for deg in (0.0, 45.0, 179.0, 180.5, 270.0, 359.0):
        v = rig.rotation_vector_unwrapped(_quat_about_z(deg))
        assert math.degrees(np.linalg.norm(v)) == pytest.approx(deg, abs=1e-6)
        assert v[2] > 0 or deg == 0.0  # about +z the whole way round, never an axis flip
    v = rig.rotation_vector_unwrapped([0.0, 0.0, -math.sin(0.1), -math.cos(0.1)])  # w < 0 kept as given
    assert math.degrees(np.linalg.norm(v)) == pytest.approx(360.0 - math.degrees(0.2), abs=1e-6)
    assert not rig.rotation_vector_unwrapped([0.0, 0.0, 0.0, 1.0]).any()


def _random_clip(rng, swing_deg):
    keys = []
    for index in range(0, 40, 10):
        rotations = {}
        for joint in rig.ROTATED:
            axis = rng.normal(size=3)
            axis /= np.linalg.norm(axis)
            deg = rng.uniform(0, swing_deg if "elbow" in joint or "knee" in joint else 60.0)
            half = math.radians(deg) / 2
            rotations[joint] = [*(math.sin(half) * axis), math.cos(half)]
        keys.append({"index": index, "local_rotations": rotations})
    return keys


def test_a_folded_elbow_twist_is_taken_out_before_the_step_is_measured():
    """An elbow swung 150 degrees about one axis and then twisted about the forearm: Part 4 drops the twist."""
    keys = _keys([(0, 0.0), (10, 0.0)])
    swing = _quat_about([1, 0, 0], 150.0)
    keys[0]["local_rotations"]["left_elbow"] = swing
    keys[1]["local_rotations"]["left_elbow"] = [float(c) for c in rig.quat_mul(_quat_about([0, 1, 0], 170.0), swing)]
    ours = rig.long_way(keys)
    assert ours == []  # without the twist drop this elbow steps 222 degrees
    assert ours == [{"joint": s[0], "from_index": s[1], "to_index": s[2], "deg": round(s[3], 1)}
                    for s in part4rules.long_way_steps(keys)]


def test_the_guard_matches_the_independent_part4_rules_on_random_clips():
    rng = np.random.default_rng(43)
    refused = 0
    for _ in range(300):
        keys = _random_clip(rng, 175.0)
        ours = [(s["joint"], s["from_index"], s["to_index"], s["deg"]) for s in rig.long_way(keys)]
        theirs = [(j, a, b, round(d, 1)) for j, a, b, d in part4rules.long_way_steps(keys)]
        assert ours == theirs
        refused += bool(ours)
    assert 0 < refused < 300  # the comparison sees both outcomes


def test_childless_joints_hold_the_identity_whatever_their_rotation():
    keys = _keys([(0, 0.0), (10, 0.0)])
    keys[0]["local_rotations"]["left_wrist"] = _quat_about([1, 0, 0], 170.0)
    keys[1]["local_rotations"]["left_wrist"] = _quat_about([0, 0, 1], 170.0)
    assert rig.long_way(keys) == [] and part4rules.long_way_steps(keys) == []


PINNED_PART4 = Path("/home/gingy/simon-part-7/modules/part-4/src")


@pytest.fixture(scope="module")
def pinned():
    """Part 4's own `simon_anim.interpolate` from Part 7's pinned copy; the tests skip when it is absent."""
    if not (PINNED_PART4 / "simon_anim" / "interpolate.py").is_file():
        pytest.skip("Part 7's modules/part-4 is not on this machine")
    sys.path.insert(0, str(PINNED_PART4))
    try:
        from simon_anim import interpolate
    finally:
        sys.path.remove(str(PINNED_PART4))
    return interpolate


def test_pinned_part4_rotvec_unwrapped_and_drop_twist_agree_on_random_quaternions(pinned):
    rng = np.random.default_rng(7)
    for _ in range(200):
        q, ref = (rng.normal(size=4) for _ in range(2))
        q, ref, axis = q / np.linalg.norm(q), ref / np.linalg.norm(ref), rng.normal(size=3)
        theirs = pinned._rotvec_unwrapped(tuple(q))
        assert np.allclose(rig.rotation_vector_unwrapped(q), theirs, atol=1e-9)
        dropped = pinned._drop_twist(tuple(q), tuple(ref), tuple(axis))
        assert np.allclose(rig.drop_twist(q, ref, axis / np.linalg.norm(axis)), dropped, atol=1e-9)


def test_pinned_part4_refuses_exactly_the_clips_the_guard_refuses(pinned):
    rng = np.random.default_rng(11)
    offsets = rig.rest_offsets({b: v for b, v in rig.standard.bone_lengths().items()})
    rest = {j: (e["parent"], tuple(e["offset"])) for j, e in offsets.items()}
    seen = set()
    for _ in range(300):
        keys = _random_clip(rng, 175.0)
        skeleton = {"keyframes": [{"index": k["index"], "t": k["index"] / 30, "local_rotations": k["local_rotations"]}
                                  for k in keys]}
        indices, times, series = pinned._keyframe_quats(skeleton, rest)
        try:
            pinned._prepare_curves(indices, times, series)
            theirs = False
        except ValueError:
            theirs = True
        ours = bool(rig.long_way(keys, offsets))
        assert ours == theirs
        seen.add(ours)
    assert seen == {True, False}
