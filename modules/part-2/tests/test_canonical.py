import numpy as np
import pytest

from part2.body3d import project
from part2.canonical import OneEuro, convert, project_pose3d
from part2.joints import CANONICAL
from part2.schema import validate_pose3d, validate_tracks

# A standing subject in the canonical frame (x = subject's left, y = up, z = anterior), metres.
BODY = {
    "nose": [0, 0.62, 0.10], "left_eye": [0.03, 0.66, 0.08], "right_eye": [-0.03, 0.66, 0.08],
    "left_ear": [0.07, 0.64, 0.0], "right_ear": [-0.07, 0.64, 0.0],
    "left_shoulder": [0.19, 0.45, 0], "right_shoulder": [-0.19, 0.45, 0],
    "left_elbow": [0.22, 0.18, 0], "right_elbow": [-0.22, 0.18, 0],
    "left_wrist": [0.24, -0.05, 0.05], "right_wrist": [-0.24, -0.05, 0.05],
    "left_hip": [0.1, 0, 0], "right_hip": [-0.1, 0, 0],
    "left_knee": [0.1, -0.45, 0.02], "right_knee": [-0.1, -0.45, 0.02],
    "left_ankle": [0.1, -0.88, -0.03], "right_ankle": [-0.1, -0.88, -0.03],
}
K = [[1000.0, 0, 640], [0, 1000.0, 360], [0, 0, 1]]


def _yaw(deg):
    """Canonical -> OpenCV camera for a subject turned `deg` from facing the camera."""
    a = np.radians(deg)
    facing = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], float)  # left=+x_cam, up=-y_cam, anterior=-z_cam
    turn = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    return facing @ turn


def _body3d(yaws, t=(0.1, 0.3, 4.0)):
    can = np.array([BODY[j] for j in CANONICAL])
    frames = []
    for i, deg in enumerate(yaws):
        cam = can @ _yaw(deg).T + np.array(t)
        uv = project(cam, K)
        frames.append({"frame": i, "t_ms": i * 33.3, "people": [{
            "id": 0, "bbox": [0, 0, 1, 1],
            "kp3d_cam": {j: p.tolist() for j, p in zip(CANONICAL, cam)},
            "kp2d": {j: q.tolist() for j, q in zip(CANONICAL, uv)}}]})
    return {"camera_frame": "opencv", "K": K, "image_size": [1280, 720], "frames": frames}


@pytest.mark.parametrize("deg", [0, 90, -90, 180, 35])
def test_canonical_frame_recovers_body_from_any_view(deg):
    pose3d, _ = convert(_body3d([deg]))
    joints = pose3d["frames"][0]["people"][0]["joints"]
    got = np.array([[joints[j][k] for k in "xyz"] for j in CANONICAL])
    np.testing.assert_allclose(got, [BODY[j] for j in CANONICAL], atol=1e-3)


def test_axes_semantics():
    joints = convert(_body3d([0]))[0]["frames"][0]["people"][0]["joints"]
    hips_mid = [(joints["left_hip"][k] + joints["right_hip"][k]) / 2 for k in "xyz"]
    np.testing.assert_allclose(hips_mid, 0, atol=1e-4)
    assert joints["left_hip"]["x"] > 0  # x = subject's left
    assert joints["nose"]["y"] > joints["left_ankle"]["y"]  # y = up
    assert joints["nose"]["z"] > 0  # z = anterior


@pytest.mark.parametrize("deg", [0, 90, 150])
def test_roundtrip_canonical_to_pixels(deg):
    b = _body3d([deg])
    pose3d, camera = convert(b)
    uv = project_pose3d(pose3d, camera)[(0, 0)]
    for j in CANONICAL:
        np.testing.assert_allclose(uv[j], b["frames"][0]["people"][0]["kp2d"][j], atol=0.05)


def test_offscreen_joints_get_low_conf():
    b = _body3d([0], t=(0.1, 1.2, 2.0))  # feet below the image
    joints = convert(b)[0]["frames"][0]["people"][0]["joints"]
    assert joints["left_ankle"]["conf"] < 1 and joints["nose"]["conf"] == 1


def test_smoothing_keeps_static_pose_and_damps_jitter():
    b = _body3d([0] * 10)
    rng = np.random.default_rng(0)
    for f in b["frames"]:
        for j in CANONICAL:
            f["people"][0]["kp3d_cam"][j] = (np.array(f["people"][0]["kp3d_cam"][j]) + rng.normal(0, 0.01, 3)).tolist()
    raw = np.array([f["people"][0]["joints"]["nose"]["x"] for f in convert(b)[0]["frames"]])
    sm = np.array([f["people"][0]["joints"]["nose"]["x"] for f in convert(b, smooth=True)[0]["frames"]])
    assert np.std(np.diff(sm)) < np.std(np.diff(raw))


def test_one_euro_passes_constant_signal():
    f = OneEuro(1.0, 0.5)
    for i in range(5):
        out = f(np.array([2.0]), i / 30)
    assert out[0] == pytest.approx(2.0)


def test_validators_reject_bad_documents():
    pose3d, _ = convert(_body3d([0]))
    validate_pose3d(pose3d)
    del pose3d["frames"][0]["people"][0]["joints"]["nose"]
    with pytest.raises(ValueError, match="17 canonical joints"):
        validate_pose3d(pose3d)
    good = {"frames": [{"frame": 0, "people": [{"id": 1, "bbox": [0, 0, 5, 9], "mask_rle": {"size": [9, 5], "counts": "a1"}, "confidence": 0.9}]}]}
    validate_tracks(good)
    good["frames"][0]["people"].append(dict(good["frames"][0]["people"][0]))
    with pytest.raises(ValueError, match="duplicate ids"):
        validate_tracks(good)


def test_degenerate_hips_drop_person_not_clip():
    b = _body3d([0, 0])
    p = b["frames"][1]["people"][0]
    p["kp3d_cam"]["right_hip"] = list(p["kp3d_cam"]["left_hip"])
    pose3d, camera = convert(b)
    assert len(pose3d["frames"][0]["people"]) == 1 and pose3d["frames"][1]["people"] == []
    assert camera["frames"][1]["people"] == [] and "level camera" in camera["world_up"]


def test_validate_tracks_ranges():
    def doc(**kw):
        p = {"id": 1, "bbox": [0, 0, 5, 9], "mask_rle": {"size": [9, 5], "counts": "a1"}, "confidence": 0.9, **kw}
        return {"frames": [{"frame": 0, "people": [p]}]}

    validate_tracks(doc())
    for bad in [dict(confidence=1.5), dict(mask_rle={"size": [0, 5], "counts": "a"}), dict(mask_rle={"size": [9, 5], "counts": ""})]:
        with pytest.raises(ValueError):
            validate_tracks(doc(**bad))
