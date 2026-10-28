"""Part 4's long-way rule as `part3.rig.long_way` applies it (spec integration-contract.md AC-P02, review B2)."""

import math

import numpy as np
import pytest

from part3 import doctor, rig
from part3.schema import ContractError, LongWayError
from part3.views import part4


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


def test_ac_p02_small_steps_pass():
    assert rig.long_way(_keys([(0, 0.0), (10, 60.0), (20, 120.0), (30, 170.0)])) == []


def test_ac_p02_crossing_180_degrees_is_the_long_way():
    steps = rig.long_way(_keys([(0, 170.0), (10, 190.0)]))
    assert len(steps) == 1
    step = steps[0]
    assert step["joint"] == "left_shoulder" and (step["from_index"], step["to_index"]) == (0, 10)
    assert step["deg"] > 180.0


def test_ac_p02_rotation_vector_angle_is_0_to_180():
    for deg in (0.0, 45.0, 179.0, 181.0, 300.0):
        v = rig.rotation_vector(_quat_about_z(deg))
        assert 0.0 <= math.degrees(np.linalg.norm(v)) <= 180.0 + 1e-9


def test_ac_p02_a_negated_quaternion_is_the_same_key():
    keys = _keys([(0, 30.0), (10, 40.0)])
    keys[1]["local_rotations"]["left_shoulder"] = [-c for c in keys[1]["local_rotations"]["left_shoulder"]]
    assert rig.long_way(keys) == []


def test_the_part4_views_refusal_is_a_long_way_error_with_the_step_as_attributes():
    keys = _keys([(0, 170.0), (10, 190.0)])
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
        part4._check_long_way(_keys([(0, 170.0), (10, 190.0)]))
    assert caught.value.msg.endswith(f"; {rig.LONG_WAY_FIX}")
