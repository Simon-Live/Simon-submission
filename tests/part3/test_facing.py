"""Step 5: the body-based frame removes camera tilt and azimuth (AC-006, unit level; ADR-0004)."""

import numpy as np
import pytest

from clipkit import doc_arrays, make_doc, skeleton_arrays
from part3 import cli, facing, geometry
from part3.joints import INDEX

TILTS = [(15, 8), (-20, 3), (12, -5), (20, -8)]  # (pitch about x, roll about z) in degrees
UNIT_UP = np.array([0.0, 1.0, 0.0])


def camera_rotation(pitch, roll, azimuth=0.0):
    return (geometry.rotation([0, 0, 1], roll) @ geometry.rotation([1, 0, 0], pitch)
            @ geometry.rotation([0, 1, 0], azimuth))


def recorded(J, conf, R):
    """What Part 2 would write for a camera whose frame is rotated by R against the body's world.

    Body points are rotated into the camera, then every frame is put into its own pelvis frame with
    the camera's up (+y). Also returns the true up (the rule on the clean frames, step 5 item 3)
    expressed in each recorded frame.
    """
    camera = J @ R.T
    framed, valid = geometry.pelvis_frame(camera, UNIT_UP)
    assert valid.all()
    axes, _ = geometry.pelvis_axes(camera, UNIT_UP)
    truth_up = geometry.body_up(J)[0]
    per_frame = np.einsum("nij,j->ni", axes, R @ truth_up)
    return make_doc(framed, conf), geometry.normalize(per_frame.mean(axis=0)), per_frame


def directions(skeleton):
    """Unit vectors of the trunk and leg bones per frame: spine, both thighs, both shanks."""
    J, _, present = skeleton_arrays(skeleton)
    assert present.all()
    p = geometry.point
    pairs = [("root", "neck"), ("left_hip", "left_knee"), ("right_hip", "right_knee"),
             ("left_knee", "left_ankle"), ("right_knee", "right_ankle")]
    return np.stack([geometry.normalize(p(J, b) - p(J, a)) for a, b in pairs], axis=1)


@pytest.fixture(scope="module")
def untilted(real_doc):
    return cli.process(real_doc)


@pytest.mark.parametrize("pitch,roll", TILTS)
def test_tilt_is_removed(real_doc, untilted, pitch, roll):
    J, conf = doc_arrays(real_doc)
    doc, true_up, per_frame = recorded(J, conf, camera_rotation(pitch, roll))
    assert geometry.angle_between(per_frame, true_up).max() < 1.0  # the true up is one vector in the clip
    assert geometry.angle_between(true_up, UNIT_UP) > 5.0  # the tilt is real: the camera up is wrong

    trace = {}
    out = cli.process(doc, trace=trace)
    assert trace["up_source"] == "standing_frames" == out["frame"]["up_source"]
    assert np.isclose(np.linalg.norm(trace["up_in_input"]), 1.0)
    assert geometry.angle_between(trace["up_in_input"], true_up) < 3.0

    delta = geometry.angle_between(directions(out), directions(untilted))
    assert delta.max() < 3.0


@pytest.mark.parametrize("azimuth", [45.0, 90.0, 180.0, -135.0])
def test_camera_azimuth_is_removed(real_doc, untilted, azimuth):
    J, conf = doc_arrays(real_doc)
    doc, _, _ = recorded(J, conf, camera_rotation(0.0, 0.0, azimuth))
    delta = geometry.angle_between(directions(cli.process(doc)), directions(untilted))
    assert delta.max() < 1.0


def test_output_has_left_hip_at_positive_x_and_face_ahead(real_doc):
    J, conf = doc_arrays(real_doc)
    doc, _, _ = recorded(J, conf, camera_rotation(15, 8, 60))
    out_J, _, present = skeleton_arrays(cli.process(doc))
    assert present.all()
    assert (out_J[:, INDEX["left_hip"], 0] > 0).all() and (out_J[:, INDEX["right_hip"], 0] < 0).all()
    hip_line = out_J[:, INDEX["left_hip"]] - out_J[:, INDEX["right_hip"]]
    assert geometry.angle_between(hip_line, [1.0, 0.0, 0.0]).max() < 8.0  # hip line along x
    ears_z = 0.5 * (out_J[:, INDEX["left_ear"], 2] + out_J[:, INDEX["right_ear"], 2])
    assert (out_J[:, INDEX["nose"], 2] > ears_z).all()  # face at positive z
    spine = geometry.point(out_J, "neck") - geometry.point(out_J, "root")
    assert (spine[:, 1] > 0).all()  # y is up: the shoulders are above the hips


def test_output_hip_line_has_no_component_along_z(untilted):
    """x is the hip line with its up component removed, so the hip line stays in the x-y plane."""
    out_J, _, _ = skeleton_arrays(untilted)
    assert np.allclose(out_J[:, INDEX["left_hip"], 2], 0.0, atol=1e-4)
    assert np.allclose(out_J[:, INDEX["right_hip"]], -out_J[:, INDEX["left_hip"]], atol=1e-4)


def test_no_standing_frames_uses_all_frames(real_doc):
    J, conf = doc_arrays(real_doc)
    bent = np.flatnonzero(~np.all(geometry.knee_angles(J) > geometry.STANDING_KNEE_DEG, axis=1))
    assert len(bent) > 20
    doc = make_doc(J[bent], conf[bent], frame_ids=bent.tolist())
    trace = {}
    out = cli.process(doc, trace=trace)
    assert out["frame"]["up_source"] == "all_frames" == trace["up_source"]
    assert not np.any(np.all(geometry.knee_angles(J[bent]) > 160, axis=1))
    expected, source = geometry.body_up(J[bent])
    assert source == "all_frames" and np.allclose(trace["up_in_input"], expected)


def test_fewer_than_five_standing_frames_uses_all_frames(real_doc):
    J, conf = doc_arrays(real_doc)
    standing = np.flatnonzero(np.all(geometry.knee_angles(J) > geometry.STANDING_KNEE_DEG, axis=1))
    bent = np.flatnonzero(~np.isin(np.arange(len(J)), standing))
    keep = np.sort(np.concatenate([standing[:4], bent]))
    assert cli.process(make_doc(J[keep], conf[keep], frame_ids=keep.tolist()))["frame"]["up_source"] == "all_frames"
    keep = np.sort(np.concatenate([standing[:5], bent]))
    assert cli.process(make_doc(J[keep], conf[keep], frame_ids=keep.tolist()))["frame"]["up_source"] == "standing_frames"


def test_real_fixture_uses_standing_frames_and_up_near_vertical(real_doc):
    trace = {}
    out = cli.process(real_doc, trace=trace)
    assert out["frame"]["up_source"] == "standing_frames"
    assert geometry.angle_between(trace["up_in_input"], UNIT_UP) < 6.0


def test_body_frame_function_matches_geometry(real_doc):
    J, _ = doc_arrays(real_doc)
    framed, valid, up, source = facing.body_frame(J)
    expected_up, expected_source = geometry.body_up(J)
    assert valid.all() and source == expected_source and np.allclose(up, expected_up)
    assert np.allclose(framed, geometry.pelvis_frame(J, up)[0])


def test_the_camera_up_is_never_used(real_doc):
    """Frames that differ only by what the camera's up is give the same skeleton."""
    J, conf = doc_arrays(real_doc)
    first, _, _ = recorded(J, conf, camera_rotation(10, 0))
    second, _, _ = recorded(J, conf, camera_rotation(-10, 6))
    a, b = (skeleton_arrays(cli.process(d))[0] for d in (first, second))
    assert np.abs(a - b).max() < 0.05  # joints (metres) agree: direction differences are under a few degrees
