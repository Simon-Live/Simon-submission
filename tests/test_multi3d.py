import json

import numpy as np
from test_canonical import BODY, _body3d

from part2.canonical import convert
from part2.joints import CANONICAL
from part2.multi3d import split_people, tracks_to_boxes, write_pose_streams


def test_tracks_to_boxes_for_body3d():
    tracks = {"frames": [
        {"frame": 0, "people": [{"id": 2, "bbox": [1, 2, 3, 4], "mask_rle": {"size": [4, 3], "counts": "a"}, "confidence": 0.9}]},
        {"frame": 5, "people": []}]}
    assert tracks_to_boxes(tracks) == {0: {2: [1.0, 2.0, 3.0, 4.0]}, 5: {}}


def _two_person_body3d():
    b = _body3d([0, 30])
    for f in b["frames"]:  # second person: same body shifted in camera space
        p0 = f["people"][0]
        p1 = {"id": 7, "bbox": [10, 10, 5, 5],
              "kp3d_cam": {j: (np.array(v) + [1.5, 0, 0]).tolist() for j, v in p0["kp3d_cam"].items()},
              "kp2d": {j: [v[0] + 50, v[1]] for j, v in p0["kp2d"].items()}}
        f["people"].append(p1)
    return b


def test_write_pose_streams_combined_and_per_person(tmp_path):
    res = write_pose_streams(_two_person_body3d(), tmp_path)
    assert res["people"] == [0, 7]
    pose = json.loads((tmp_path / "pose3d.json").read_text())
    assert [sorted(p["id"] for p in f["people"]) for f in pose["frames"]] == [[0, 7], [0, 7]]
    assert (tmp_path / "camera.json").exists()
    for pid in (0, 7):
        doc = json.loads((tmp_path / f"pose3d_person_{pid}.json").read_text())
        assert all([p["id"] for p in f["people"]] == [pid] for f in doc["frames"])
        assert set(doc["frames"][0]["people"][0]["joints"]) == set(CANONICAL)


def test_split_people_keeps_frame_alignment():
    pose3d, _ = convert(_two_person_body3d())
    streams = split_people(pose3d)
    assert [f["frame"] for f in streams[7]["frames"]] == [0, 1]
    # the camera-space shift is absorbed by the hip-midpoint origin, so the
    # canonical poses match while the streams stay separate per id
    assert streams[7]["frames"][1]["people"][0]["joints"] == \
        streams[0]["frames"][1]["people"][0]["joints"]
