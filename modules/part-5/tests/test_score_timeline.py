"""ADR-0013: the score is the mean of windows, so it is a share of the take and not points per mistake."""
import numpy as np
import pytest

from part5 import score
from part5 import cues, profiles
from part5.detect import load_rules
from part5.insights import insights_of
from part5.measures import MEASURES
from shipped_score import UNMEASURED_TEMPO, tempo_items, v1_only

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


@v1_only   # v2 and v3 cap the value and weight the points: tests/test_score_v2.py and tests/test_score_v3.py pin it before the cap
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


@v1_only   # a weighted miss costs fractional points, shown to 0.1: tests/test_score_v2.py and tests/test_score_v3.py add them up to 0.6
def test_each_window_lists_its_misses_and_they_add_up_to_its_value():
    block = _take(30, 3)
    assert block["basis"] == "windows" and len(block["timeline"]) == 6
    for w in block["timeline"]:
        assert w["value"] == round(100 - sum(m["points"] for m in w["misses"]) - w["components"]["similarity"])
        for m in w["misses"]:
            assert m["text"] and m["points"] > 0 and w["t_s"][0] - 1 <= m["at_s"] <= w["t_s"][1]
    assert block["value"] == round(sum(w["value"] for w in block["timeline"]) / 6)


# --- one window, made in one place for a whole-clip take and for a take compared rep by rep (ADR-0014, ADR-0016) ----
NO_CHARGE = {"cues": {}, "weight": 0.0, "cap": 0.0}
DANCE_CHARGE = {"cues": {}, "weight": 40.0, "cap": 20.0}


def _scored_window(tempo=NO_CHARGE, ratio=1.0, timed=True, frames=None, faults=None):
    n = 90
    analysis = {"status": {"code": "ok"}, "faults": [] if faults is None else faults}
    frames = np.arange(n) if frames is None else frames
    return score.timeline_window((0.0, 3.0), analysis, _aligned(n), frames, RULES, score.params_of(RULES), tempo, ratio, timed)


def test_a_window_with_nothing_to_score_is_only_shown():
    assert _scored_window(frames=np.arange(0)) == {"t_s": (0.0, 3.0), "compared": False}


def test_a_window_is_the_window_score_under_t_s_with_its_tempo_block_when_timed():
    w = _scored_window(ratio=1.0)
    assert list(w)[0] == "t_s" and w["t_s"] == (0.0, 3.0) and "compared" not in w
    assert w["tempo"]["ratio"] == 1.0 and "tempo" not in w["components"]          # the plain rules charge no tempo
    plain = score.window_score({"status": {"code": "ok"}, "faults": []}, _aligned(90), np.arange(90), RULES,
                               score.params_of(RULES))
    assert {k: v for k, v in w.items() if k not in ("t_s", "tempo")} == plain
    assert "tempo" not in _scored_window(ratio=1.0, timed=False)                         # an untimed take has no tempo block


def test_only_a_profile_that_charges_tempo_charges_the_window_for_it():
    off, on = _scored_window(NO_CHARGE, ratio=1.4), _scored_window(DANCE_CHARGE, ratio=1.4)
    assert "tempo" not in off["components"] and on["components"]["tempo"] == pytest.approx(10.0)   # 40 per 1.0 outside 1.15 + band
    assert on["value"] == off["value"] - 10
    unmeasured = _scored_window(DANCE_CHARGE, ratio=None)
    assert unmeasured["components"]["tempo"] == 0.0 and unmeasured["tempo"]["ratio"] is None


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


# --- ADR-0014 Amendment 4 (TICKET-063): a take whose match is low has no tempo ----------------------------------
# The rule lives in `score.tempo_ratio`; the end to end cases (a half speed fixture take, the rep basis) are in
# tests/test_profiles_tempo.py and tests/test_reps.py.
LOW_MATCH = {"match": {"quality": "low", "residual": 0.62, "timing_corr": 0.9, "limits": {}}}
OK_MATCH = {"match": {"quality": "ok", "residual": 0.2, "timing_corr": 0.95, "limits": {}}}


def _stretched_take(match, profile, stretch=2.0, n=300, fps=30):
    """A take whose aligned frames span `stretch` times the example's 10 s (the tempo ratio; 2.0 plays it in 20 s, 0.6 in 6 s),
    compared as a whole, under `profile`'s rules; `match` is the document's `match` block (a low one when the take was not
    matched to the example)."""
    rules = profiles.effective_rules(RULES, profile)
    analysis = {"status": {"code": "ok"}, "faults": [], **match}
    return score.compute_timeline(analysis, _aligned(n), np.arange(n) * stretch / fps, rules, expected_times=np.arange(n) / fps)


def _insights(block):
    """The document `tempo_items` reads: the insights of a take with no faults and this score block."""
    return {"insights": insights_of({"faults": [], "score": block})}


def test_tempo_ratio_is_the_span_ratio_unless_the_match_is_low():
    assert score.tempo_ratio(OK_MATCH, [0, 4], [0, 2]) == 2.0 and score.tempo_ratio({}, [0, 4], [0, 2]) == 2.0
    assert score.tempo_ratio(LOW_MATCH, [0, 4], [0, 2]) is None
    assert score.low_match(LOW_MATCH) and not score.low_match(OK_MATCH) and not score.low_match({"match": None})


@pytest.mark.parametrize("profile", profiles.names())
def test_a_low_match_has_no_tempo_in_the_take_or_any_window_or_the_insights(profile):
    low = _stretched_take(LOW_MATCH, profile)
    windows = [w for w in low["timeline"] if w["compared"]]
    assert low["basis"] == "windows" and len(windows) == 4
    assert low["tempo"] == UNMEASURED_TEMPO and all(w["tempo"] == UNMEASURED_TEMPO for w in windows)
    assert tempo_items(_insights(low)) == []


@pytest.mark.parametrize("profile", profiles.names())
def test_a_match_of_quality_ok_keeps_its_tempo_in_the_take_every_window_and_the_insights(profile):
    ok = _stretched_take(OK_MATCH, profile)
    words = profiles.tempo_of(profiles.effective_rules(RULES, profile))["cues"]
    assert ok["tempo"] == cues.tempo_block(2.0, words) and ok["tempo"]["ratio"] == 2.0 and ok["tempo"]["cue"]
    assert all(w["tempo"] == ok["tempo"] for w in ok["timeline"])
    shown = [] if profile == "rehab" else [ok["tempo"]["cue"]]   # rehab's "Slower is fine" is a reassurance, so no item
    assert [i["cue"] for i in tempo_items(_insights(ok))] == shown
    assert _stretched_take({}, profile)["tempo"] == ok["tempo"]                  # a document with no match block is not a low one


def test_a_low_match_is_charged_no_tempo_under_dance_and_an_ok_one_is():
    low, ok = _stretched_take(LOW_MATCH, "dance"), _stretched_take(OK_MATCH, "dance")
    assert low["components"]["tempo"] == 0.0 and all(w["components"]["tempo"] == 0.0 for w in low["timeline"])
    assert ok["components"]["tempo"] == 20.0 and all(w["components"]["tempo"] == 20.0 for w in ok["timeline"])   # the cap
    assert low["value"] == ok["value"] + 20 and tempo_items(_insights(low)) == [] and tempo_items(_insights(ok))[0]["points"] == 20.0
    for profile in ("fitness", "rehab"):   # these charge no tempo, so a low match changes no value
        assert _stretched_take(LOW_MATCH, profile)["value"] == _stretched_take(OK_MATCH, profile)["value"]
        assert "tempo" not in _stretched_take(LOW_MATCH, profile)["components"]


@pytest.mark.parametrize("profile", profiles.names())
def test_a_low_match_whose_take_spans_less_time_than_the_example_is_never_told_to_slow_down(profile):
    """Part 7's inverted shape (staging job 1538d81126c2): the example played 6.9 s, the take 23.9 s, and the alignment mapped
    the whole example onto 4.53 s of the take, so the ratio read 0.66 and the cue "Slow down" on a take that was too slow.
    Here the follower time the alignment spans is 0.6 of the example's (6 s over 10 s). The same input at quality ok gives a
    ratio under 0.85 and the slow-down cue, which proves it is the inverted shape; on a low match the take's tempo, every
    window's and the insights hold neither the cue nor a ratio."""
    ok, low = _stretched_take(OK_MATCH, profile, stretch=0.6), _stretched_take(LOW_MATCH, profile, stretch=0.6)
    ok_windows, low_windows = ([w["tempo"] for w in b["timeline"] if w["compared"]] for b in (ok, low))
    assert ok_windows and len(ok_windows) == len(low_windows)
    assert all(t["ratio"] < cues.TEMPO_FAST and t["cue"] == cues.SLOW_DOWN for t in [ok["tempo"], *ok_windows])
    assert [i["cue"] for i in tempo_items(_insights(ok))] == [cues.SLOW_DOWN]
    assert all(t == UNMEASURED_TEMPO for t in [low["tempo"], *low_windows])
    assert tempo_items(_insights(low)) == [] and cues.SLOW_DOWN not in [i["cue"] for i in _insights(low)["insights"]]
