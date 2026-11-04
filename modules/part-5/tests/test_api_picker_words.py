"""The picker words every label in the analysis's timed words, without the time (docs/specs/staging.md AC-S10, walkthrough
review R9, TICKET-057). The foot takes were worded this way first (tests/test_api.py); this covers every measure."""
import json
import re
from pathlib import Path

from part5 import api, words
from part5.evaluate import canonical_label
from part5.real import KIT_TYPE_MAP

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
KIT = json.loads((ROOT / "fixtures/input/contract/part3/followers/labels.json").read_text())
KIT_SET = "part3-squat"
FOOT_TAKE = next(t for t in LABELS["takes"] if t["take_id"] == "exercise_front_good_03_foot_out-right")
# words.QUALIFIERS spelled out: the measured size, which a label does not know and the picker therefore leaves out.
SIZE_WORDS = [("slightly ", ""), ("much ", ""), (" slightly", ""), (" a lot", ""), ("not quite", "not"), ("nowhere near", "not")]
TIME_TAIL = re.compile(r" at \d+\.\d s$")


def call(method, path, payload=None):
    status, _, out = api.handle(method, path, b"" if payload is None else json.dumps(payload).encode(), base_path="/")
    return status, json.loads(out)


def listed_followers():
    return {t["id"]: t for t in call("GET", "/api/samples")[1]["followers"]}


def analyse(set_name, take_id):
    status, body = call("POST", "/api/analyse", {"expected": {"sample": set_name}, "follower": {"sample": take_id}})
    assert status == 200, take_id
    return body["analysis"]


def sentence(text):
    return text[:1].upper() + text[1:]


def kit_key(label):
    """(measure, side, direction) of a kit label as the real-take report matches it: the kit type map, the label's side."""
    measure, direction = KIT_TYPE_MAP[label["type"]]
    return measure, label["side"], direction


def without_the_time_and_the_size_word(text_timed):
    """The analysis's `text_timed` as a picker can say it: no " at N s", and no quality word."""
    text = TIME_TAIL.sub("", text_timed)
    for size_word, plain in SIZE_WORDS:
        text = text.replace(size_word, plain)
    return text


def test_the_size_words_are_the_ones_the_analysis_uses():
    spelled = {w for q, nq, aq in words.QUALIFIERS.values() for w in (q, nq, aq) if w and w not in ("", "not")}
    assert spelled == {w for w, _ in SIZE_WORDS}


def test_a_correct_take_keeps_its_words_and_a_label_the_analysis_has_no_words_for_keeps_its_own_text():
    followers = listed_followers()
    for take in LABELS["takes"]:
        if not take["faults"]:
            assert followers[take["take_id"]]["label"].endswith(": Correct take"), take["take_id"]
            assert followers[take["take_id"]]["faults"] == []
    # the Part 3 kit's types are worded through real.KIT_TYPE_MAP, on the label's own side
    kit = {"type": "feet_wide", "measure": "ankle_lateral_offset", "side": "both", "direction": "more", "text": "feet too wide"}
    assert api._fault_text(kit) == "feet too far apart" == words.phrase_timed("foot_out", "more", "both")
    assert api._fault_text({**kit, "type": "elbows_out", "measure": "upper_arm_abduction"}) == "elbows wider than the example"
    assert api._fault_text({**kit, "type": "shallow_squat", "direction": "less"}) == "knees not bent enough"
    # a label of a vocabulary neither map knows, or one with no direction or a side its measure does not take, is shown
    # as written
    for fault in ({"type": "odd", "measure": "ankle_lateral_offset", "side": "both", "direction": "more", "text": "odd words"},
                  {"type": "odd", "measure": "knee_flexion", "side": "left", "direction": None, "text": "knee odd"},
                  {"type": "odd", "measure": "knee_flexion", "side": "center", "direction": "less", "text": "bad side"}):
        assert api._fault_text(fault) == fault["text"]


def test_every_generated_label_is_worded_as_the_analysis_words_it_timed_and_the_label_files_are_unchanged():
    followers = listed_followers()
    assert len(LABELS["takes"]) == 156
    for take in LABELS["takes"]:
        listed = followers[take["take_id"]]
        assert len(listed["faults"]) == len(take["faults"])
        for given, shown in zip(take["faults"], listed["faults"]):
            measure, side, direction = canonical_label(given)
            want = words.phrase_timed(measure, direction, side)
            assert shown == {"type": given["type"], "side": side, "text": want}, take["take_id"]   # the label's own type and side
        what = "; ".join(f["text"] for f in listed["faults"]) or "correct take"
        assert listed["label"].endswith(f": {sentence(what)}"), (take["take_id"], listed["label"])
    # the label ids and the file read as before: "too far out" is the label's, "too far right" the page's
    assert FOOT_TAKE["faults"][0]["text"] == "right foot too far out"


def test_take_03_is_listed_as_too_far_right_and_never_as_too_far_out_while_its_result_says_too_far_right():
    """The finding (walkthrough review R9): the picker said "Right foot too far out" over a result that said "too far right"."""
    listed = listed_followers()[FOOT_TAKE["take_id"]]
    assert listed["label"] == "Take 03: Right foot too far right" and listed["faults"][0]["text"] == "right foot too far right"
    assert "too far out" not in listed["label"] and "too far out" not in listed["faults"][0]["text"]
    foot = [f for f in analyse("exercise", FOOT_TAKE["take_id"])["faults"] if f["measure"] == "foot_out"]
    assert len(foot) == 1 and foot[0]["lateral"] == "right" and "too far right" in foot[0]["text_timed"]
    assert "too far out" not in foot[0]["text_timed"]


def test_for_every_good_light_take_whose_analysis_reports_its_labelled_fault_the_picker_words_are_its_timed_words():
    """The picker words, in sentence case, are the fault's `text_timed` without " at N s" (and without the size word, which
    only the analysis measures). Checked on every seed 5 good light take whose analysis reports the labelled fault on the
    label's own side, so a label that names both sides is not held to the one side the analysis reported."""
    followers = listed_followers()
    checked, kinds = 0, set()
    cases = [(take, take["set"], canonical_label) for take in LABELS["takes"] if take["lighting"] == "good"]
    cases += [(take, KIT_SET, kit_key) for take in KIT["takes"]]            # the Part 3 kit, against its own squat
    for take, expected, key in cases:
        if not take["faults"]:
            continue
        reported_faults = analyse(expected, take["take_id"])["faults"]
        for position, given in enumerate(take["faults"]):
            measure, side, direction = key(given)
            reported = [f for f in reported_faults if (f["measure"], f["direction"], f["side"]) == (measure, direction, side)]
            if not reported:
                continue
            picked = followers[take["take_id"]]["faults"][position]["text"]
            assert sentence(picked) == sentence(without_the_time_and_the_size_word(reported[0]["text_timed"])), take["take_id"]
            assert followers[take["take_id"]]["label"].endswith(sentence(picked)) or len(take["faults"]) > 1, take["take_id"]
            checked += 1
            kinds.add((given["type"], reported[0].get("lateral")))
    assert checked >= 50, checked                                           # not a vacuous pass: most takes report their fault
    assert {kind for kind, _ in kinds} >= {"foot_out", "arms_wider", "elbow_bent", "knee_caving", "knees_shallow", "trunk_lean",
                                           "foot_turned_out", "foot_turned_in", "ankle_rolled_in", "ankle_rolled_out",
                                           "feet_wide", "elbows_out", "shallow_squat"}
    assert {lateral for kind, lateral in kinds if kind in ("foot_out", "arms_wider")} >= {"left", "right"}   # lateral derived both ways


def test_no_picker_label_of_a_kit_take_keeps_the_kits_own_old_words():
    followers = listed_followers()
    old = ("Feet too wide", "Elbows too far out", "Knees not bent enough at the bottom", "caves in")
    for take in KIT["takes"]:
        label = followers[take["take_id"]]["label"]
        assert not any(words_ in label for words_ in old), (take["take_id"], label)
        assert label in ("Correct take", "Feet too far apart", "Elbows wider than the example", "Knees not bent enough",
                         "Left knee caving in", "Right knee caving in"), label
