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


# --- the acceptance criteria of ADR-0013 (docs/adr/ADR-0013-score-timeline-length-agnostic.md) ------------------
def _spans(seconds, fps=30):
    n = int(seconds * fps)
    block = score.compute_timeline({"status": {"code": "ok"}, "faults": []}, _aligned(n), np.arange(n) / fps, RULES)
    return block["timeline"]


@pytest.mark.parametrize("seconds,windows", [(3, 1), (7.4, 1), (7.8, 2), (30, 6), (62, 12)])
def test_ac_tl01_a_whole_clip_take_is_cut_into_max_1_round_span_over_5_windows(seconds, windows):
    assert len(_spans(seconds)) == windows


def test_ac_tl01_the_windows_tile_the_followers_span_without_gaps():
    spans = [w["t_s"] for w in _spans(30)]
    assert spans[0][0] == 0.0 and spans[-1][1] == pytest.approx(29.967, abs=0.001)
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))


def _window(raw, faults=0.0, similarity=0.0):
    return {"t_s": (0.0, 5.0), "raw": raw, "value": int(raw), "grade": score.grade(int(raw)),
            "components": {"faults": faults, "similarity": similarity}, "misses": []}


def test_ac_tl02_a_window_that_was_not_compared_is_shown_and_not_scored():
    block = score.timeline_block([_window(90.0), {"t_s": (5.0, 10.0), "compared": False}, _window(80.0)], "reps", RULES)
    assert block["value"] == 85 and block["basis"] == "reps"
    assert [w["compared"] for w in block["timeline"]] == [True, False, True]
    assert all("raw" not in w for w in block["timeline"])


def test_ac_tl02_with_no_window_compared_the_score_is_zero_and_the_timeline_is_still_listed():
    block = score.timeline_block([{"t_s": (0.0, 5.0), "compared": False}], "reps", RULES)
    assert (block["value"], block["grade"], block["basis"]) == (0, "F", "reps")
    assert block["timeline"] == [{"t_s": [0.0, 5.0], "compared": False}]


def test_ac_tl03_the_warning_cap_applies_after_the_mean_and_keeps_the_timeline():
    block = score.timeline_block([_window(95.0), _window(97.0)], "windows", RULES)
    capped = score.cap_by_warnings(block, {"warnings": [{"code": "low_match", "text": "x"}]}, RULES)
    assert block["value"] == 96 and capped["value"] == 59 and capped["grade"] == "F"
    assert capped["capped_by"] == ["low_match"] and capped["basis"] == "windows"
    assert capped["timeline"] == block["timeline"] and capped["components"] == block["components"]


def test_ac_tl04_basis_and_timeline_are_in_the_published_schema():
    import json
    from pathlib import Path

    import jsonschema
    root = Path(__file__).resolve().parent.parent
    schema = json.loads((root / "contracts/analysis.schema.json").read_text())["properties"]["score"]
    block = score.timeline_block([_window(90.0)], "windows", RULES)
    jsonschema.Draft202012Validator(schema).validate(block)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(dict(block, basis="minutes"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(dict(block, timeline=[{"t_s": [0.0], "compared": True}]))
