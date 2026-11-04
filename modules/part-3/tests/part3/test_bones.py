"""Step 6: one standard body (AC-004; ADR-0004)."""

import json

import numpy as np
import pytest

from clipkit import doc_arrays, make_doc, skeleton_arrays
from part3 import bones, cli, standard
from part3.joints import BONE_NAMES, INDEX
from part3.standard import STANDARD_BODY_PATH

STD = json.loads(STANDARD_BODY_PATH.read_text())
STD_LENGTHS = np.array([STD["bone_lengths_m"][name] for name in BONE_NAMES])


def scaled(real_doc, factor):
    J, conf = doc_arrays(real_doc)
    return make_doc(J * factor, conf)


@pytest.mark.parametrize("factor", [1.0, 0.8, 1.2])
def test_every_frame_matches_the_standard_table_within_half_a_percent(real_doc, factor):
    doc = real_doc if factor == 1.0 else scaled(real_doc, factor)
    skeleton = cli.process(doc)
    J, _, present = skeleton_arrays(skeleton)
    assert present.all()
    lengths = bones.measure(J)
    assert np.abs(lengths / STD_LENGTHS - 1).max() < 0.005


def test_output_names_the_standard_body_of_the_file(real_doc):
    skeleton = cli.process(real_doc)
    assert skeleton["bone_lengths_m"] == STD["bone_lengths_m"]
    assert list(skeleton["bone_lengths_m"]) == list(BONE_NAMES)
    assert skeleton["standard"]["stature_m"] == STD["stature_m"] == 1.7
    assert skeleton["standard"]["sources"] == list(STD["sources"].values())
    assert standard.bone_lengths() == STD["bone_lengths_m"]


def test_bone_lengths_are_the_same_for_any_input_body_size(real_doc):
    small, large = cli.process(scaled(real_doc, 0.8)), cli.process(scaled(real_doc, 1.2))
    assert small["bone_lengths_m"] == large["bone_lengths_m"]
    for name, length in small["person"]["measured_bone_lengths_m"].items():
        assert length == pytest.approx(large["person"]["measured_bone_lengths_m"][name] * 0.8 / 1.2, abs=2e-4)


def test_measured_lengths_are_kept_for_context(real_doc):
    J, conf = doc_arrays(real_doc)
    measured = cli.process(real_doc)["person"]["measured_bone_lengths_m"]
    assert list(measured) == list(BONE_NAMES)
    assert measured["left_thigh"] == pytest.approx(float(np.median(bones.measure(J)[:, 2])), abs=1e-4)
    # right_ankle has conf 0.3 in every frame: under 10% qualify, so the right shank uses all frames.
    assert (conf[:, 16] < 1).all()
    assert measured["right_shank"] == pytest.approx(float(np.median(bones.measure(J)[:, 5])), abs=1e-4)


def test_measured_lengths_use_only_full_confidence_frames_when_enough_qualify():
    J = np.zeros((10, 17, 3))
    J[:, 11, 0], J[:, 12, 0] = 0.1, -0.1  # hips
    J[:, 13] = J[:, 11] + [0, -0.5, 0]  # left knee under the left hip
    J[5:, 13] = J[5:, 11] + [0, -0.9, 0]  # frames 5-9 have a longer thigh
    conf = np.ones((10, 17))
    conf[5:, 13] = 0.3  # ... and a low-confidence knee
    assert standard.measured_bone_lengths(J, conf)["left_thigh"] == pytest.approx(0.5)
    conf[1:, 13] = 0.3  # one trusted frame in ten is exactly 10%: still counts
    assert standard.measured_bone_lengths(J, conf)["left_thigh"] == pytest.approx(0.5)
    conf[:, 13] = 0.3  # none trusted: all frames, median of 0.5 x5 and 0.9 x5
    assert standard.measured_bone_lengths(J, conf)["left_thigh"] == pytest.approx(0.7)


def test_root_and_neck_bones_need_both_hips_and_both_shoulders_trusted():
    J = np.zeros((10, 17, 3))
    J[:, 11, 0], J[:, 12, 0] = 0.1, -0.1
    J[:, 5], J[:, 6] = [0.2, 0.5, 0], [-0.2, 0.5, 0]
    J[5:, 5, 1] = 0.9  # left shoulder higher in frames 5-9 (spine = root to neck midpoint)
    conf = np.ones((10, 17))
    conf[5:, 12] = 0.3  # right hip low confidence from frame 5
    spine = standard.measured_bone_lengths(J, conf)["spine"]
    assert spine == pytest.approx(0.5)  # only frames 0-4 qualify


def test_retarget_keeps_input_directions(real_doc):
    J, _ = doc_arrays(real_doc)
    out = bones.retarget(J, STD_LENGTHS)
    for name, a, b in [("left_forearm", "left_elbow", "left_wrist"), ("right_shank", "right_knee", "right_ankle")]:
        d_in = J[:, INDEX[b]] - J[:, INDEX[a]]
        d_out = out[:, INDEX[b]] - out[:, INDEX[a]]
        cos = np.sum(d_in * d_out, axis=1) / (np.linalg.norm(d_in, axis=1) * np.linalg.norm(d_out, axis=1))
        assert cos.min() > 0.999999, name
