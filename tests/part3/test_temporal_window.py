"""Step 5b window in time (spec part3-skeleton.md step 5b, ASM-018)."""
import json
from pathlib import Path

import numpy as np
import pytest

from part3 import cli, temporal

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("fps, width", [(15, 5), (5, 1), (30, 9), (25, 9), (60, 19), (10, 3),
                                        (1, 1), (240, 79)])
def test_window_spans_a_third_of_a_second(fps, width):
    assert temporal.window_for([i * 1000.0 / fps for i in range(20)]) == width


def test_window_without_two_times_keeps_the_calibrated_width():
    assert temporal.window_for([0.0]) == temporal.WINDOW == 5
    assert temporal.window_for([]) == 5


def test_window_reads_the_median_step_so_one_late_frame_does_not_change_it():
    times = [i * 200.0 for i in range(10)] + [1960.0]
    assert temporal.window_for(times) == 1


def _real():
    return json.loads((ROOT / "fixtures/input/part2-single/pose3d.json").read_text())


def _knee(doc):
    out = []
    for f in doc["frames"]:
        j = {n: np.array([v["x"], v["y"], v["z"]]) for n, v in f["people"][0]["joints"].items()}
        a, b = j["left_hip"] - j["left_knee"], j["left_ankle"] - j["left_knee"]
        out.append(np.degrees(np.arccos(a @ b / np.linalg.norm(a) / np.linalg.norm(b))))
    return np.array(out)


def test_a_five_fps_clip_keeps_its_angles():
    """Every third frame of the 15 fps squat is a 5 fps clip: no filter, so the knee angle of each
    output frame equals the input's to rounding (a 5-frame filter would span 1 s)."""
    doc = _real()
    doc["frames"] = doc["frames"][::3]
    out = cli.process(doc)
    assert np.max(np.abs(_knee(out) - _knee(doc))) < 0.1


def test_the_fifteen_fps_clip_is_filtered_as_before():
    doc = _real()
    assert temporal.window_for([f["t_ms"] for f in doc["frames"]]) == 5
