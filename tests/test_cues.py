"""ADR-0014: coaching cues on faults and misses, tempo per window and per take, and the top-level insights."""
import json
import re
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5 import cues, doctor, score
from part5.detect import load_rules
from part5.insights import MAX_INSIGHTS, insights_of
from part5.measures import MEASURES
from part5.output import GENERIC_MEASURES, OutputError, _spec, validate_analysis
from part5.pipeline import run
from part5.score_report import score_block

ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules()
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
EXAMPLE = ROOT / "fixtures/output/analysis.example.json"
SEED5 = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
LATERAL = ROOT / "fixtures/input/real/lateral-raise"
DASHES = re.compile("[–—]| - ")


def _combos():
    for measure in GENERIC_MEASURES:
        for side in ("left", "right", "both", "center"):
            if _spec(measure, side) is None:
                continue
            for direction in ("more", "less"):
                yield measure, direction, side


# --- the vocabulary --------------------------------------------------------------------------------------
def test_every_measure_direction_and_side_the_contract_allows_has_a_short_imperative_cue():
    seen = set()
    for measure, direction, side in _combos():
        cue, kind = cues.cue_for(measure, direction, side)
        assert 1 <= len(cue.split()) <= cues.MAX_WORDS, cue
        assert cue[0].isupper() and not cue.endswith(".") and not DASHES.search(cue), cue
        assert kind in ("position", "range")
        if side in ("left", "right"):
            assert side in cue.split(), cue        # the subject's own side is named
        seen.add(cue)
    assert len(seen) > 40   # distinct advice, not one line for everything


def test_opposite_directions_give_different_cues():
    for measure, _, side in _combos():
        assert cues.cue_for(measure, "more", side) != cues.cue_for(measure, "less", side)


@pytest.mark.parametrize("measure,direction,side,want", [
    ("knee_flexion", "less", "both", "Bend your knees more"),
    ("upper_arm_out", "less", "left", "Raise your left arm higher"),
    ("trunk_lean_forward", "less", "center", "Lean forward more"),
    ("thigh_forward", "less", "both", "Lower your hips more"),
    ("knee_valgus", "more", "right", "Push your right knee out"),
])
def test_the_cues_say_what_to_do_toward_the_example(measure, direction, side, want):
    assert cues.cue_for(measure, direction, side)[0] == want


@pytest.mark.parametrize("args", [("ankle_twist", "more", "left"), ("knee_flexion", "up", "left"),
                                  ("knee_flexion", "less", "center"), ("trunk_lean_forward", "more", "left")])
def test_a_cue_outside_the_vocabulary_is_an_error(args):
    with pytest.raises(ValueError):
        cues.cue_for(*args)


def test_nothing_measures_the_foot_beyond_the_ankle_so_no_cue_claims_it():
    assert not any("foot" in m and "rot" in m or "ankle" in m for m in MEASURES)
    for measure, direction, side in _combos():
        cue = cues.cue_for(measure, direction, side)[0].lower()
        assert "twist" not in cue and "ankle" not in cue and "toe" not in cue and "heel" not in cue


@pytest.mark.parametrize("ratio,want", [(None, None), (0.5, cues.SLOW_DOWN), (0.849, cues.SLOW_DOWN), (0.85, None),
                                        (1.0, None), (1.15, None), (1.151, cues.SPEED_UP), (2.3, cues.SPEED_UP)])
def test_tempo_cue_thresholds(ratio, want):
    assert cues.tempo_cue(ratio) == want


def test_tempo_block_rounds_then_decides():
    assert cues.tempo_block(0.8461) == {"ratio": 0.85, "cue": None}
    assert cues.tempo_block(None) == {"ratio": None, "cue": None}


# --- tempo from the alignment ------------------------------------------------------------------------------
def test_span_ratio_is_follower_seconds_per_example_second_and_none_when_too_short():
    assert score.span_ratio([0, 4], [0, 2]) == 2.0
    assert score.span_ratio([0, 0.4], [0, 0.5]) is None   # under MIN_TEMPO_S of the example
    assert score.span_ratio([1.0], [1.0]) is None


@pytest.mark.parametrize("take_id", ["exercise_front_good_08", "exercise_front_good_03", "exercise_front_good_00"])
def test_take_tempo_matches_the_generators_known_speed(take_id):
    """The dummy followers play the example at a known `speed`, so the follower takes 1/speed of its time."""
    take = next(t for t in SEED5["takes"] if t["take_id"].startswith(take_id))
    a = run(str(ROOT / take["expected"]), str(ROOT / take["follower"]), score=score_block).analysis
    assert a["score"]["tempo"]["ratio"] == pytest.approx(1 / take["speed"], abs=0.05)
    for w in a["score"]["timeline"]:
        assert w["tempo"]["cue"] == cues.tempo_cue(w["tempo"]["ratio"])


@pytest.fixture(scope="module")
def fast():
    """The real lateral raise: the trainer's three slow reps against a follower's eight fast ones (ADR-0010)."""
    return run(str(LATERAL / "pexels-5319084/animation.json"), str(LATERAL / "pexels-40297504/animation.json"),
               score=score_block).analysis


def test_a_follower_much_faster_than_the_trainer_is_told_to_slow_down_per_rep_and_for_the_take(fast):
    jsonschema.Draft202012Validator(SCHEMA).validate(fast)
    s = fast["score"]
    assert s["basis"] == "reps" and s["tempo"]["ratio"] < 0.5 and s["tempo"]["cue"] == cues.SLOW_DOWN
    assert all(w["tempo"]["cue"] == cues.SLOW_DOWN for w in s["timeline"] if w["compared"])
    tempo = [x for x in fast["insights"] if x["kind"] == "tempo"]
    assert len(tempo) == 1 and fast["insights"][-1] == tempo[0] and tempo[0]["points"] is None
    assert tempo[0]["why"].startswith("Your reps took") and tempo[0]["at_s"] is not None


def test_every_miss_on_the_timeline_carries_its_feedback_and_cue(fast):
    misses = [m for w in fast["score"]["timeline"] for m in w.get("misses", [])]
    assert misses
    for m in misses:
        assert m["text"] and m["cue"] == cues.cue_for(m["measure"], m["direction"], m["side"])[0]
        assert m["cue_kind"] in ("position", "range") and m["points"] > 0


def test_rep_insights_are_ranked_by_their_share_of_the_score(fast):
    items = [x for x in fast["insights"] if x["kind"] != "tempo"]
    assert len(fast["insights"]) <= MAX_INSIGHTS and items
    assert [x["points"] for x in items] == sorted((x["points"] for x in items), reverse=True)
    lost = 100 - fast["score"]["value"]
    assert sum(x["points"] for x in items) <= lost + 1
    for x in items:
        assert re.search(r"\(\d+ of 8 reps\)$", x["why"]) and not DASHES.search(x["why"])
        w = fast["score"]["timeline"][x["window"]]
        assert any(m["cue"] == x["cue"] and m["at_s"] == x["at_s"] for m in w["misses"])


# --- insights from a timeline, synthetic -----------------------------------------------------------------
def _miss(cue, at, points, measure="knee_flexion", side="both", direction="less"):
    return {"text": "x", "measure": measure, "side": side, "joint": "knee", "t_s": [at, at + 1], "at_s": at,
            "points": points, "cue": cue, "cue_kind": "range", "direction": direction}


def _timeline_doc(windows, basis="windows", tempo=None):
    return {"faults": [], "score": {"basis": basis, "timeline": windows,
                                    **({"tempo": tempo} if tempo else {})}}


def test_window_insights_sum_points_over_compared_windows_and_point_at_the_first_miss():
    w = [{"t_s": [0, 5], "misses": [_miss("Bend your knees more", 1.0, 10.0)]},
         {"t_s": [5, 10], "compared": False},
         {"t_s": [10, 15], "misses": [_miss("Bend your knees more", 12.0, 20.0),
                                      _miss("Keep your chest up", 11.0, 4.0, "trunk_lean_forward", "center", "more")]}]
    got = insights_of(_timeline_doc(w))
    assert [x["cue"] for x in got] == ["Bend your knees more", "Keep your chest up"]
    assert got[0]["points"] == 15.0 and got[0]["at_s"] == 1.0 and got[0]["window"] == 0
    assert got[0]["why"] == "Knees not bent enough (2 times, first at 1.0 s)"
    assert got[1]["why"] == "Leaning forward more than the example at 11.0 s" and got[1]["window"] == 2


def test_at_most_five_insights_and_a_tempo_insight_keeps_its_place():
    many = [_miss(f"Cue number {i}", float(i), 10.0 - i) for i in range(8)]
    plain = insights_of(_timeline_doc([{"t_s": [0, 5], "misses": many}]))
    assert len(plain) == MAX_INSIGHTS and plain[0]["cue"] == "Cue number 0"
    tempo = {"ratio": 1.4, "cue": cues.SPEED_UP}
    w = [{"t_s": [0, 5], "misses": many, "tempo": {"ratio": 1.2, "cue": cues.SPEED_UP}},
         {"t_s": [5, 10], "misses": [], "tempo": {"ratio": 1.6, "cue": cues.SPEED_UP}}]
    got = insights_of(_timeline_doc(w, tempo=tempo))
    assert len(got) == MAX_INSIGHTS and got[-1]["kind"] == "tempo" and got[-1]["window"] == 1
    assert got[-1]["at_s"] == 5 and got[-1]["why"] == "You took 1.4 times the trainer's time"


def test_misses_written_before_cues_give_no_insights():
    old = {k: v for k, v in _miss("Bend your knees more", 1.0, 5.0).items() if k not in ("cue", "cue_kind")}
    assert insights_of(_timeline_doc([{"t_s": [0, 5], "misses": [old]}])) == []


def test_without_a_timeline_insights_follow_the_faults_with_no_points():
    a = json.loads(EXAMPLE.read_text())
    assert a["schema_version"] == "1.5.0" and "score" not in a
    assert [x["cue"] for x in a["insights"]] == [f["cue"] for f in a["faults"]]
    assert all(x["points"] is None and x["window"] is None for x in a["insights"])
    assert a["insights"][0]["why"] == "Right elbow bent more than the example at 0.7 s"


# --- the length-agnostic score keeps its cues (ADR-0013) --------------------------------------------------
def test_one_miss_a_minute_and_ten_in_ten_minutes_cost_about_the_same_share():
    def take(seconds, misses, fps=30):
        n = seconds * fps
        starts = np.linspace(0, n - fps, misses, dtype=int)
        faults = [{"measure": "elbow_flexion", "side": "left", "joint": "left_elbow", "direction": "more",
                   "magnitude_deg": 30.0, "threshold_deg": 20.0, "runs": [[int(s), int(s) + fps - 1]],
                   "expected_frames": [int(s), int(s) + fps - 1], "coverage": 1.0, "text": "left elbow bent",
                   "cue": "Straighten your left arm more", "cue_kind": "range", "at_s": s / fps,
                   "follower_t_s": [s / fps, s / fps + 1]} for s in starts]
        zeros = {name: np.zeros(n) for name in MEASURES}
        t = np.arange(n) / fps
        block = score.compute_timeline({"status": {"code": "ok"}, "faults": faults},
                                       {"expected": zeros, "follower": zeros, "exp_to_fol": np.arange(n)}, t,
                                       RULES, expected_times=t)
        return block, insights_of({"faults": faults, "score": block})

    (one, one_ins), (ten, ten_ins) = take(60, 1), take(600, 10)
    assert abs(one["value"] - ten["value"]) <= 3
    assert one_ins[0]["points"] == pytest.approx(ten_ins[0]["points"], abs=0.5)
    assert one["tempo"] == {"ratio": 1.0, "cue": None} and all(x["kind"] != "tempo" for x in ten_ins)


# --- the contract ----------------------------------------------------------------------------------------
def _with(**over):
    a = json.loads(EXAMPLE.read_text())
    a.update(over)
    return a


@pytest.mark.parametrize("bad,needle", [
    (lambda a: a["faults"][0].update(cue="Straighten your right arm a lot more now"), "at most 6 words"),
    (lambda a: a["faults"][0].update(cue_kind="tempo"), "cue_kind must be one of"),
    (lambda a: a["faults"][0].pop("cue_kind"), "cue_kind must be one of"),
    (lambda a: a.update(insights=[{"cue": "Go"}] * 6), "at most 5"),
    (lambda a: a["insights"][0].update(why=""), "why must be a non-empty string"),
    (lambda a: a["insights"][0].update(kind="speed"), "kind must be one of"),
    (lambda a: a["insights"][0].update(window=-1), "window must be a window index"),
    (lambda a: a["insights"][0].update(at_s="soon"), "at_s must be a number or null"),
])
def test_validate_analysis_names_a_broken_cue_or_insight(bad, needle):
    a = _with()
    bad(a)
    with pytest.raises(OutputError, match=needle):
        validate_analysis(a)


def test_the_schema_accepts_the_new_fields_and_an_older_document_without_them():
    v = jsonschema.Draft202012Validator(SCHEMA)
    v.validate(json.loads(EXAMPLE.read_text()))
    old = json.loads(EXAMPLE.read_text())
    old.pop("insights")
    for f in old["faults"]:
        f.pop("cue"), f.pop("cue_kind")
    v.validate(dict(old, schema_version="1.2.0"))
    validate_analysis(dict(old, schema_version="1.2.0"))
    long = json.loads(EXAMPLE.read_text())
    long["faults"][0]["cue"] = "one two three four five six seven"
    assert list(v.iter_errors(long))


def test_doctor_accepts_cues_for_part7_notes_a_document_without_them_and_rejects_a_broken_one(tmp_path):
    r = doctor.inspect_file(EXAMPLE, "part7")
    assert r.exit_code == 0 and not any("1.5.0" in n for n in r.notes)
    old = json.loads(EXAMPLE.read_text())
    old.pop("insights")
    p = tmp_path / "old.json"
    p.write_text(json.dumps(old))
    assert any("written before 1.5.0" in n for n in doctor.inspect_file(p, "part7").notes)
    broken = json.loads(EXAMPLE.read_text())
    broken["insights"][0]["kind"] = "speed"
    p.write_text(json.dumps(broken))
    assert doctor.inspect_file(p, "part7").exit_code != 0
