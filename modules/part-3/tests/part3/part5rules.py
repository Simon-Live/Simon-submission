"""Test support: Part 5's documented input rules applied to a part5 view (not a test module)."""

import math

from part3.joints import JOINTS

COORDINATE_FRAME = {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
                    "position_unit": "metres", "angle_unit": "degrees"}


def part5_input_rules(doc):
    """Part 5's documented input rules (its docs/schemas.md and part5/io.py) applied to `doc`; returns None or raises."""
    assert isinstance(doc, dict)
    assert doc.get("format") in ("simon.animation.v1", "simon.skeleton.v1")
    frame_block = doc.get("coordinate_frame", {})
    assert isinstance(frame_block, dict)
    for key, value in COORDINATE_FRAME.items():
        assert key not in frame_block or frame_block[key] == value
    assert "joints" not in doc or doc["joints"] == list(JOINTS)
    fps = doc.get("fps")
    assert fps is None or (isinstance(fps, (int, float)) and not isinstance(fps, bool) and fps > 0)
    frames = doc["frames"]
    assert isinstance(frames, list) and frames
    times, hips = [], []
    for k, frame in enumerate(frames):
        assert isinstance(frame["t"], (int, float)) and not isinstance(frame["t"], bool)
        assert isinstance(frame.get("interpolated", False), bool)
        joints = frame["joints"]
        assert isinstance(joints, dict) and set(joints) <= set(JOINTS)
        conf = frame.get("conf", {})
        assert isinstance(conf, dict) and set(conf) <= set(JOINTS)
        assert all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in conf.values())
        for name, point in joints.items():
            assert isinstance(point, list) and len(point) == 3
            assert all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in point)
        times.append(frame["t"])
        hips.append([(joints["left_hip"][a] + joints["right_hip"][a]) / 2 for a in range(3)])
    assert all(b > a for a, b in zip(times, times[1:])), "frame times must strictly increase"
    assert max(abs(c) for hip in hips for c in hip) <= 0.01, "hip midpoint must be at the origin"
