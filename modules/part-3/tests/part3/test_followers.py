"""Follower takes for Part 5 (AC-K03): faults applied in the body frame, found again in Part 3's native output."""

import json

import numpy as np
import pytest

from clipkit import make_doc
from conftest import REAL_CLIP
from part3 import bones, cli, followers, synth
from part3.followers import FAULT_ORDER, KINDS, take_defs
from part3.geometry import knee_angles
from part3.joints import INDEX

DEFS = take_defs()
FAULT_DEFS = [td for td in DEFS if td.fault]
CORRECT_DEFS = [td for td in DEFS if td.fault is None]


@pytest.fixture(scope="module")
def src():
    return synth.load_source()


@pytest.fixture(scope="module")
def natives(src):
    """Native skeleton (the pipeline's output) of every take, by take id."""
    return {td.take_id: cli.process(followers.pose3d_for(src, td)) for td in DEFS}


@pytest.fixture(scope="module")
def reference():
    return cli.process(json.loads(REAL_CLIP.read_text()))


def as_doc(J):
    return make_doc(J, np.ones(J.shape[:2]))


def correct_of(td):
    return next(c for c in CORRECT_DEFS if c.angle == td.angle)


# ---- the take list --------------------------------------------------------------------------------

def test_there_are_fifteen_takes_three_correct_and_four_faults_at_three_angles():
    assert len(DEFS) == 15 and len(CORRECT_DEFS) == 3 and len(FAULT_DEFS) == 12
    assert {td.angle for td in DEFS} == {"front", "45", "side"}
    assert {td.fault for td in FAULT_DEFS} == set(FAULT_ORDER) == {"feet_wide", "elbows_out", "shallow_squat",
                                                                    "knee_caving"}
    for angle in ("front", "45", "side"):
        assert sorted(td.fault or "" for td in DEFS if td.angle == angle) == sorted(("",) + FAULT_ORDER)


def test_ids_and_random_streams_are_unique_and_clear_of_the_synthetic_set():
    assert len({td.take_id for td in DEFS}) == 15
    streams = [td.stream for td in DEFS]
    assert len(set(streams)) == 15 and not set(streams) & {1, 2, 3, 4, synth.ARMRAISE_TAKE}


def test_one_fault_touches_one_side_only_and_the_others_both():
    sided = {td.fault: set() for td in FAULT_DEFS}
    for td in FAULT_DEFS:
        sided[td.fault].add(td.side)
    assert sided["feet_wide"] == sided["elbows_out"] == sided["shallow_squat"] == {"both"}
    assert sided["knee_caving"] == {"left", "right"}


def test_a_take_is_deterministic(src):
    td = FAULT_DEFS[0]
    assert followers.pose3d_for(src, td) == followers.pose3d_for(src, td)


def test_input_is_a_part2_shaped_pose3d_at_15_fps(src):
    doc = followers.pose3d_for(src, FAULT_DEFS[0])
    assert len(doc["frames"]) == len(src.frames) == 107
    assert [f["t_ms"] for f in doc["frames"][:3]] == [0.0, 66.667, 133.333]
    assert list(doc["frames"][0]["people"][0]["joints"]["nose"]) == ["x", "y", "z", "conf"]


# ---- the fault in the body frame -----------------------------------------------------------------

@pytest.mark.parametrize("td", FAULT_DEFS, ids=lambda td: td.take_id)
def test_a_fault_keeps_every_bone_length(src, td):
    clean = synth.truth_at(src, np.arange(len(src.frames)) / synth.FPS)
    faulted = followers.apply_fault(clean, td.fault, td.size, td.side, src.lengths)
    assert np.abs(bones.measure(faulted) - src.lengths).max() < 1e-9
    assert not np.allclose(faulted, clean)


@pytest.mark.parametrize("td", FAULT_DEFS, ids=lambda td: td.take_id)
def test_the_applied_size_is_recovered_exactly_in_the_body_frame(src, td):
    clean = synth.truth_at(src, np.arange(len(src.frames)) / synth.FPS)
    faulted = followers.apply_fault(clean, td.fault, td.size, td.side, src.lengths)
    by_side = followers.sizes(td.fault, as_doc(faulted), as_doc(clean))
    for name, _ in followers.sides(td.side):
        assert by_side[name] == pytest.approx(td.size, rel=1e-6)
    for name in {"left", "right"} - {n for n, _ in followers.sides(td.side)}:
        assert abs(by_side[name]) < 1e-6


def test_squat_depth_is_zero_standing_and_one_at_the_bottom(src):
    w = followers.depth_weight(knee_angles(src.frames).mean(axis=-1))
    assert w.min() == 0.0 and w.max() == 1.0
    assert w[0] < 0.5 < w[35]  # frame 35 is the first bottom of the real squat


def test_shallow_squat_and_knee_caving_leave_a_standing_frame_alone(src):
    clean = synth.truth_at(src, np.arange(len(src.frames)) / synth.FPS)
    for fault in ("shallow_squat", "knee_caving"):
        faulted = followers.apply_fault(clean, fault, KINDS[fault].size, "both", src.lengths)
        standing = np.flatnonzero(followers.depth_weight(knee_angles(clean).mean(axis=-1)) == 0.0)[0]
        assert np.abs(faulted[standing] - clean[standing]).max() < 1e-9


def test_elbows_out_moves_the_forearm_with_the_elbow(src):
    clean = synth.truth_at(src, np.arange(len(src.frames)) / synth.FPS)
    faulted = followers.apply_fault(clean, "elbows_out", 20.0, "both", src.lengths)
    for side in ("left", "right"):
        fore = lambda J: J[:, INDEX[f"{side}_wrist"]] - J[:, INDEX[f"{side}_elbow"]]  # noqa: E731
        assert np.abs(fore(faulted) - fore(clean)).max() < 1e-12


def test_sides_follow_the_label():
    assert [n for n, _ in followers.sides("left")] == ["left"]
    assert [n for n, _ in followers.sides("right")] == ["right"]
    assert [n for n, _ in followers.sides("both")] == ["left", "right"]


# ---- AC-K03: visible in Part 3's native output ---------------------------------------------------

@pytest.mark.parametrize("td", FAULT_DEFS, ids=lambda td: td.take_id)
def test_ac_k03_a_fault_survives_normalisation_within_half_its_size_on_the_labelled_side(natives, td):
    value, by_side = followers.measured_sizes(td, natives[td.take_id], natives[correct_of(td).take_id])
    labelled = {n for n, _ in followers.sides(td.side)}
    for name, size in by_side.items():
        if name in labelled:
            assert 0.5 * td.size <= size <= 1.5 * td.size, (name, size)
        else:
            assert abs(size) < 0.5 * td.size, (name, size)
    assert 0.5 * td.size <= value <= 1.5 * td.size


@pytest.mark.parametrize("td", CORRECT_DEFS, ids=lambda td: td.take_id)
def test_ac_k03_a_correct_take_shows_no_fault_against_the_real_squat(natives, reference, td):
    for fault, kind in KINDS.items():
        for name, size in followers.sizes(fault, natives[td.take_id], reference).items():
            assert abs(size) < kind.threshold, (fault, name, size)


def test_the_measure_reports_the_wrong_side_when_left_and_right_are_swapped(natives):
    """A left/right flip in the output turns a left-labelled fault into a right-sided one (side awareness)."""
    left = next(td for td in FAULT_DEFS if td.fault == "knee_caving" and td.side == "left")
    right = next(td for td in FAULT_DEFS if td.fault == "knee_caving" and td.angle == "45")
    by_side = followers.sizes("knee_caving", natives[right.take_id], natives[correct_of(right).take_id])
    assert by_side["right"] > 0.5 * right.size and abs(by_side["left"]) < 0.5 * right.size
    assert left.side == "left" and right.side == "right"


# ---- labels -----------------------------------------------------------------------------------------

def test_labels_use_part5_field_names_and_the_applied_sizes():
    doc = followers.labels_doc(DEFS)
    assert doc["format"] == "simon.part3.follower_labels/1"
    assert doc["angles"] == {"front": 0, "45": 45, "side": 90}
    assert [t["take_id"] for t in doc["takes"]] == [td.take_id for td in DEFS]
    for take, td in zip(doc["takes"], DEFS):
        assert {"take_id", "set", "movement", "angle", "camera_yaw_deg", "correct", "faults", "follower",
                "input"} <= set(take)
        assert take["correct"] is (td.fault is None) and take["movement"] == "squat"
        assert (take["faults"] == []) == (td.fault is None)
    fault = next(t for t in doc["takes"] if t["take_id"] == "squat_front_feet_wide")["faults"][0]
    assert fault == {"type": "feet_wide", "measure": "ankle_lateral_offset", "body_part": "legs",
                     "joints": ["left_ankle", "right_ankle"], "side": "both", "direction": "more",
                     "magnitude_m": 0.1, "text": "feet too wide"}


def test_degree_faults_carry_magnitude_deg_and_the_metre_fault_magnitude_m():
    for td in FAULT_DEFS:
        entry = followers.fault_label(td)
        unit = KINDS[td.fault].unit
        assert entry[f"magnitude_{unit}"] == td.size
        assert ("magnitude_m" in entry) == (unit == "m") and ("magnitude_deg" in entry) == (unit == "deg")
        assert "measured_in_output" not in entry


def test_measured_sizes_are_written_into_the_labels_when_known():
    measured = {td.take_id: 1.25 for td in FAULT_DEFS}
    for take in followers.labels_doc(DEFS, measured)["takes"]:
        assert all(f["measured_in_output"] == 1.25 for f in take["faults"])


def test_a_one_sided_label_names_one_joint():
    td = next(td for td in FAULT_DEFS if td.take_id == "squat_front_knee_caving-left")
    entry = followers.fault_label(td)
    assert entry["side"] == "left" and entry["joints"] == ["left_knee"] and entry["text"] == "left knee caves in at the bottom"
