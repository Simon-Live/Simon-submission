"""docs/specs/profiles.md: rehab says "Slower is fine" and leaves it out of the insights (ADR-0016).

AC-PROF-07 (the tempo cue under rehab, on the seed 5 takes and on hand-made scores) and its amendment of 2026-10-31 (a
reassurance cue is no item of "what to work on first": under rehab a slow take keeps "Slower is fine" in `tempo.cue` and
`score.tempo.cue` but `insights_of` adds no tempo item, and the place goes back to the fault items). The profiles file,
the effective rules and the other ACs are in tests/test_profiles.py; the seed 5 runs are the `seed5` fixture in
tests/conftest.py."""
import json

import pytest
import retimed

from part5 import cues, profiles
from part5.detect import load_rules
from part5.insights import MAX_INSIGHTS, insights_of
from part5.pipeline import run
from part5.score_report import score_block

from shipped_score import UNMEASURED_TEMPO, tempo_items


def take_ratio(a):
    """The take's tempo ratio, None for a take nothing could be compared on (its zero score has no tempo)."""
    return (a["score"].get("tempo") or {}).get("ratio")


def test_rehab_says_slower_is_fine_end_to_end(seed5):
    runs, _ = seed5
    slow = [t for t, a in runs["fitness"].items() if take_ratio(a) is not None and take_ratio(a) > cues.TEMPO_SLOW]
    assert slow, "no seed 5 take is slower than the example by more than 15%"
    for take_id in slow:
        fit, rehab, dance = (runs[n][take_id] for n in ("fitness", "rehab", "dance"))
        assert fit["score"]["tempo"]["cue"] == dance["score"]["tempo"]["cue"] == cues.SPEED_UP
        assert rehab["score"]["tempo"] == {"ratio": fit["score"]["tempo"]["ratio"], "cue": "Slower is fine"}
        assert tempo_items(fit)[0]["cue"] == cues.SPEED_UP and tempo_items(dance)[0]["cue"] == cues.SPEED_UP
        # Writer ruling of 2026-10-31: "Slower is fine" is a reassurance, so it is no item of "what to work on first".
        assert tempo_items(rehab) == [] and "Slower is fine" not in [i["cue"] for i in rehab["insights"]]
        for wf, wr in zip(fit["score"]["timeline"], rehab["score"]["timeline"]):
            if wf.get("tempo") and wf["tempo"]["cue"] == cues.SPEED_UP:
                assert wr["tempo"] == {"ratio": wf["tempo"]["ratio"], "cue": "Slower is fine"}
    fast = [t for t, a in runs["fitness"].items() if (take_ratio(a) or 1) < cues.TEMPO_FAST]
    for take_id in fast:   # a follower faster than the example is still told to slow down, in every profile
        assert runs["rehab"][take_id]["score"]["tempo"]["cue"] == cues.SLOW_DOWN


def test_rehab_adds_no_tempo_item_for_a_slow_take_and_keeps_the_cue(seed5):
    """Writer ruling of 2026-10-31: "What to work on first lists actions. 'Slower is fine' is a reassurance, so under
    rehab a slow tempo keeps its cue in `tempo.cue` and `score.tempo.cue` but adds no item to `insights`." """
    runs, _ = seed5
    slow = [t for t, a in runs["rehab"].items() if take_ratio(a) is not None and take_ratio(a) > cues.TEMPO_SLOW]
    assert slow
    for take_id in slow:
        a = runs["rehab"][take_id]
        assert a["score"]["tempo"]["cue"] == "Slower is fine"
        assert "Slower is fine" not in [i["cue"] for i in a["insights"]] and tempo_items(a) == []
        assert all(i["kind"] != "tempo" for i in a["insights"])


def synthetic_tempo_doc(profile, ratio, misses=0):
    """A scored take as `insights_of` reads it: one compared window at `ratio`, the cue the profile gives it."""
    words = profiles.tempo_of(profiles.effective_rules(load_rules(), profile))["cues"]
    tempo = cues.tempo_block(ratio, words)
    miss = [{"text": "x", "measure": "knee_flexion", "side": "both", "joint": "knee", "t_s": [i, i + 1], "at_s": float(i),
             "points": 10.0 - i, "cue": f"Cue number {i}", "cue_kind": "range", "direction": "less"} for i in range(misses)]
    window = {"t_s": [0, 5], "compared": True, "misses": miss, "tempo": tempo}
    return {"faults": [], "score": {"basis": "windows", "timeline": [window], "tempo": tempo}}


@pytest.mark.parametrize("profile, ratio, cue", [
    ("rehab", 1.3, None), ("rehab", 3.0, None), ("rehab", 0.7, cues.SLOW_DOWN), ("rehab", 1.0, None),
    ("fitness", 1.3, cues.SPEED_UP), ("dance", 1.3, cues.SPEED_UP), ("fitness", 0.7, cues.SLOW_DOWN),
    ("dance", 0.7, cues.SLOW_DOWN)])
def test_only_rehab_leaves_the_slow_tempo_cue_out_of_the_insights(profile, ratio, cue):
    doc = synthetic_tempo_doc(profile, ratio)
    assert [i["cue"] for i in insights_of(doc)] == ([cue] if cue else [])
    if profile == "rehab" and ratio > cues.TEMPO_SLOW:
        assert doc["score"]["tempo"] == {"ratio": ratio, "cue": "Slower is fine"}   # the cue itself is kept


def test_the_reassurance_cues_are_named_and_rehabs_replacement_is_one_of_them():
    """The rule is the named set `cues.REASSURANCE_CUES`, not "any cue but the default" (delivery review R3)."""
    rehab = profiles.tempo_of(profiles.effective_rules(load_rules(), "rehab"))["cues"]
    assert cues.REASSURANCE_CUES == frozenset({"Slower is fine"}) and rehab["speed_up"] in cues.REASSURANCE_CUES
    assert not {cues.SPEED_UP, cues.SLOW_DOWN} & cues.REASSURANCE_CUES


@pytest.mark.parametrize("cue, kept", [("Slower is fine", False), ("Pick up the pace", True), ("Speed up a little", True),
                                       (cues.SPEED_UP, True)])
def test_a_reassurance_cue_adds_no_tempo_item_and_an_action_cue_keeps_it(cue, kept):
    """A profile that wrote an action in place of the speed-up nudge keeps its item; only a reassurance drops it."""
    tempo = cues.tempo_block(1.3, {"speed_up": cue})
    assert tempo == {"ratio": 1.3, "cue": cue}
    window = {"t_s": [0, 5], "compared": True, "misses": [], "tempo": tempo}
    doc = {"faults": [], "score": {"basis": "windows", "timeline": [window], "tempo": tempo}}
    items = insights_of(doc)
    assert [i["cue"] for i in items] == ([cue] if kept else []) and all(i["kind"] == "tempo" for i in items)


def test_a_left_out_tempo_item_gives_its_place_back_to_the_other_insights():
    rehab = insights_of(synthetic_tempo_doc("rehab", 1.3, misses=7))
    fitness = insights_of(synthetic_tempo_doc("fitness", 1.3, misses=7))
    assert len(rehab) == len(fitness) == MAX_INSIGHTS
    assert fitness[-1]["kind"] == "tempo" and all(i["kind"] != "tempo" for i in rehab)
    assert [i["cue"] for i in rehab[:-1]] == [i["cue"] for i in fitness[:-1]] and rehab[-1]["cue"] == "Cue number 4"


# --- ADR-0014 Amendment 4 (TICKET-063): Part 7's half speed finding -------------------------------------------
# The unit cases of the rule (the windows, the profiles, the dance charge) are in tests/test_score_timeline.py and the rep
# basis in tests/test_reps.py. These two takes are the end to end case: a committed seed 5 follower played at half speed.
HALF_SPEED = {"exercise_front_good_00_correct": "ok", "dance_front_low_01_correct": "low"}   # take -> match.quality it gives


@pytest.fixture(scope="module")
def half_speed(tmp_path_factory):
    """`{take_id: (expected path, the take's follower written at twice its length)}`, by `retimed.retime` at speed 0.5."""
    out, labels = tmp_path_factory.mktemp("half-speed"), json.loads(retimed.LABELS.read_text())
    takes = {t["take_id"]: t for t in labels["takes"] if t["take_id"] in HALF_SPEED}
    assert set(takes) == set(HALF_SPEED)
    paths = {}
    for take_id, take in takes.items():
        source = retimed.ROOT / take["follower"]
        paths[take_id] = (str(retimed.ROOT / take["expected"]), out / f"{take_id}.json")
        retimed.retime(source, paths[take_id][1], 0.5, json.loads(source.read_text())["fps"])
    return paths


def half_speed_run(half_speed, take_id, profile):
    expected, follower = half_speed[take_id]
    return run(expected, str(follower), profile=profile, score=score_block).analysis


@pytest.mark.parametrize("take_id", sorted(HALF_SPEED))
def test_a_half_speed_take_under_rehab_is_never_told_to_slow_down(half_speed, take_id):
    """Part 7's finding (staging job 1538d81126c2): the matching clip slowed to half speed got `score.tempo` {ratio 0.66,
    "Slow down to match the trainer"} on a low match, because the ratio measured the 4.53 s of a 23.9 s take that the
    alignment covered. A tempo is never inverted: unmeasured on a low match, or above 1 with rehab's own slow cue on a good
    one. Measured with this code, the two committed takes give one of each.
    (1) exercise_front_good_00_correct at half speed is a GOOD match (quality ok, no `match` block): a ratio above 1.15
    and rehab's "Slower is fine", a reassurance, so no insight. The ratio's value is not pinned: it is the alignment's
    cover of the slowed take and moves with TICKET-064; only its direction is the claim.
    (2) dance_front_low_01_correct at half speed is a LOW match: unmeasured. Before the rule it gave ratio 1.08 and no
    cue, a figure that only the alignment's partial cover gave."""
    a = half_speed_run(half_speed, take_id, "rehab")
    quality = (a.get("match") or {}).get("quality", "ok")
    assert quality == HALF_SPEED[take_id]
    windows = [w["tempo"] for w in a["score"]["timeline"] if w["compared"]]
    assert windows and cues.SLOW_DOWN not in [t["cue"] for t in [a["score"]["tempo"], *windows]]
    assert all(t["ratio"] is None or t["ratio"] > 1 for t in [a["score"]["tempo"], *windows])   # never inverted
    assert tempo_items(a) == []
    if quality == "low":
        assert a["score"]["tempo"] == UNMEASURED_TEMPO and all(t == UNMEASURED_TEMPO for t in windows)
        assert a["warnings"][0]["code"] == "low_match" and a["score"]["grade"] == "F"
    else:
        assert all(t["ratio"] > cues.TEMPO_SLOW and t["cue"] == "Slower is fine" for t in [a["score"]["tempo"], *windows])


@pytest.mark.parametrize("profile", ["fitness", "dance"])
def test_a_half_speed_low_match_has_no_tempo_item_or_charge_under_fitness_and_dance(half_speed, profile):
    a = half_speed_run(half_speed, "dance_front_low_01_correct", profile)
    assert a["match"]["quality"] == "low" and a["score"]["tempo"] == UNMEASURED_TEMPO
    assert all(w["tempo"] == UNMEASURED_TEMPO for w in a["score"]["timeline"] if w["compared"])
    assert tempo_items(a) == [] and cues.SPEED_UP not in [i["cue"] for i in a["insights"]]
    if profile == "dance":
        assert a["score"]["components"]["tempo"] == 0.0
        assert all(w["components"]["tempo"] == 0.0 for w in a["score"]["timeline"] if w["compared"])


def test_a_half_speed_take_that_matches_keeps_its_tempo_and_the_charge_under_fitness_and_dance(half_speed):
    fit = half_speed_run(half_speed, "exercise_front_good_00_correct", "fitness")
    dance = half_speed_run(half_speed, "exercise_front_good_00_correct", "dance")
    assert fit["score"]["tempo"] == dance["score"]["tempo"]
    assert fit["score"]["tempo"]["ratio"] > cues.TEMPO_SLOW and fit["score"]["tempo"]["cue"] == cues.SPEED_UP
    assert [i["cue"] for i in tempo_items(fit)] == [i["cue"] for i in tempo_items(dance)] == [cues.SPEED_UP]
    assert dance["score"]["components"]["tempo"] > 0 and "tempo" not in fit["score"]["components"]
