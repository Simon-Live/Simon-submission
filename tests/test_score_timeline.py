"""ADR-0013: the score is the mean of windows, so it is a share of the take and not points per mistake."""
import numpy as np
import pytest

from part5 import score
from part5.detect import load_rules
from part5.measures import MEASURES

RULES = load_rules()


def _aligned(n):
    zeros = {name: np.zeros(n) for name in MEASURES}
    return {"expected": zeros, "follower": zeros, "exp_to_fol": np.arange(n)}


def _fault(start, end, at):
    return {"measure": "elbow_flexion", "side": "left", "joint": "left_elbow", "magnitude_deg": 30.0,
            "threshold_deg": 20.0, "runs": [[start, end]], "expected_frames": [start, end], "coverage": 1.0,
            "text": "left elbow bent more than the example", "follower_t_s": [at, at + 1], "at_s": at}


def _take(seconds, misses, fps=30):
    """A take of `seconds` with `misses` one-second faults spread evenly; scored in 5 s windows."""
    n = seconds * fps
    starts = np.linspace(0, n - fps, misses, dtype=int) if misses else []
    analysis = {"status": {"code": "ok"}, "faults": [_fault(int(s), int(s) + fps - 1, s / fps) for s in starts]}
    return score.compute_timeline(analysis, _aligned(n), np.arange(n) / fps, RULES)


def test_one_miss_a_minute_scores_like_ten_misses_in_ten_minutes():
    one, ten = _take(60, 1), _take(600, 10)
    assert one["value"] == pytest.approx(ten["value"], abs=1)
    assert one["value"] > _take(60, 10)["value"]                 # more misses in the same time cost more


def test_a_short_take_is_one_window_and_scores_as_compute():
    n = 90
    analysis = {"status": {"code": "ok"}, "faults": [_fault(10, 40, 0.3)]}
    block = score.compute_timeline(analysis, _aligned(n), np.arange(n) / 30, RULES)
    plain = score.compute(analysis, _aligned(n), RULES)
    assert len(block["timeline"]) == 1 and block["value"] == plain["value"]
    assert block["components"] == plain["components"]


def test_each_window_lists_its_misses_and_they_add_up_to_its_value():
    block = _take(30, 3)
    assert block["basis"] == "windows" and len(block["timeline"]) == 6
    for w in block["timeline"]:
        assert w["value"] == round(100 - sum(m["points"] for m in w["misses"]) - w["components"]["similarity"])
        for m in w["misses"]:
            assert m["text"] and m["points"] > 0 and w["t_s"][0] - 1 <= m["at_s"] <= w["t_s"][1]
    assert block["value"] == round(sum(w["value"] for w in block["timeline"]) / 6)
