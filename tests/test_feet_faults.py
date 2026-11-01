"""Foot faults, words, cues, output, doctor, score, command line and labels (docs/specs/foot-keypoints.md AC-FOOT-12 to
AC-FOOT-18, ADR-0015, TICKET-040). The side-file helpers and the input, time and hiding tests are in test_feet.py."""
import copy
import json
import math

import jsonschema
import numpy as np
import pytest

from part5 import cli, contract, cues, doctor, evaluate
from part5.detect import detect, load_rules
from part5.feet import FOOT_MIN_CONF, MIN_SEEN_SHARE, load_side, pair_of
from part5.measures import MEASURES
from part5.output import GENERIC_MEASURES, OutputError, validate_analysis
from part5.phrasing.template import line_problem
from part5.pipeline import analyse, run
from part5.score_report import score_block
from part5.words import PHRASES, describe, describe_timed, phrase
from test_feet import (EXPECTED, FOUR, FRAME_S, LABELS_SCHEMA, NO_FEET, ROOT, SCHEMA, TAKE, WITH_FEET, analyse_with,  # noqa: F401
                       foot_faults, load, plain, side_doc, write)  # noqa: F401  (plain is a fixture)


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-12: a toe-out fault; AC-FOOT-13: an ankle roll fault
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("sides,yaw,direction,side,cue", [
    ({"left": 20.0}, 20.0, "more", "left", "Turn your left foot in"),
    ({"left": -20.0}, -20.0, "less", "left", "Turn your left foot out"),
    ({"right": 20.0}, 20.0, "more", "right", "Turn your right foot in"),
    ({"left": 20.0, "right": 20.0}, 20.0, "more", "both", "Turn your feet in"),
    ({"left": -20.0, "right": -20.0}, -20.0, "less", "both", "Turn your feet out"),
])
def test_ac_foot_12_a_foot_turned_further_out_or_in_over_the_middle_is_one_rotation_fault(
        tmp_path, sides, yaw, direction, side, cue):
    a = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=side_doc(TAKE, extra_yaw=sides)).analysis
    faults = foot_faults(a)
    assert len(faults) == 1, [(f["measure"], f["side"], f["direction"]) for f in a["faults"]]
    f = faults[0]
    assert (f["measure"], f["side"], f["direction"]) == ("foot_rotation", side, direction)
    assert f["joint"] == ("ankle" if side == "both" else f"{side}_ankle") and f["body_part"] == "feet"
    assert f["measure_kind"] == "direction" and f["threshold_deg"] == 14.0
    assert f["magnitude_deg"] == pytest.approx(yaw, abs=3.0)
    assert f["cue"] == cue and f["cue_kind"] == "position"
    assert f["joints"] == ([f"left_ankle", "right_ankle"] if side == "both" else [f"{side}_ankle"])
    jsonschema.Draft202012Validator(SCHEMA).validate(a)
    validate_analysis(a)


def test_ac_foot_12_the_fault_has_the_words_the_time_and_the_lateral_of_any_fault(tmp_path):
    a = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=side_doc(TAKE, extra_yaw={"left": 20.0})).analysis
    f = foot_faults(a)[0]
    assert f["text"].startswith("left foot turned out") and "more than the example" in f["text"]
    assert f["text_timed"] == f"{f['text']} at {f['at_s']:.1f} s" and f["coaching"] == f["text_timed"]
    assert f["lateral"] == "left" and "lateral_m" not in f
    assert f["follower_t_s"][0] < f["follower_t_s"][1] and f["runs"] and f["follower_runs"]
    assert a["insights"] and a["insights"][0]["cue"] in {x["cue"] for x in a["faults"]} | {"Turn your left foot in"}


@pytest.mark.parametrize("roll,direction,cue", [
    (25.0, "more", "Keep your left ankle straight"),
    (-25.0, "less", "Stop your left ankle rolling in"),
])
def test_ac_foot_13_a_foot_rolled_over_the_middle_is_one_ankle_inversion_fault(tmp_path, roll, direction, cue):
    a = analyse_with(tmp_path, expected=side_doc(EXPECTED),
                     follower=side_doc(TAKE, extra_roll={"left": roll})).analysis
    faults = foot_faults(a)
    assert len(faults) == 1, [(f["measure"], f["side"], f["direction"]) for f in a["faults"]]
    f = faults[0]
    assert (f["measure"], f["side"], f["direction"]) == ("ankle_inversion", "left", direction)
    assert f["joint"] == "left_ankle" and f["body_part"] == "feet" and f["threshold_deg"] == 14.0
    assert f["magnitude_deg"] == pytest.approx(roll, abs=4.0) and f["cue"] == cue
    assert f["lateral"] == ("left" if direction == "more" else "right")    # more: the outer edge, the fault's own side
    jsonschema.Draft202012Validator(SCHEMA).validate(a)


def test_ac_foot_13_a_roll_does_not_read_as_a_rotation(tmp_path):
    rolled = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=side_doc(TAKE, extra_roll={"left": 25.0}))
    assert {f["measure"] for f in foot_faults(rolled.analysis)} == {"ankle_inversion"}


def test_ac_foot_12_a_foot_turned_far_out_under_a_knee_that_travels_straight_forward_reads_no_ankle_roll(tmp_path):
    """The first, shin-relative definition read a roll here (the shin leans forward in the squat and a foot turned
    25 degrees puts that lean partly across the foot's long axis; spec Why This Is Wrong, 5). The roll against world
    up does not read the shin: the planted foot stays flat, so only the rotation is reported."""
    turned = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=side_doc(TAKE, extra_yaw={"left": 25.0}))
    got = {(f["measure"], f["side"], f["direction"]) for f in foot_faults(turned.analysis)}
    assert got == {("foot_rotation", "left", "more")}


def test_ac_foot_12_a_differently_turned_pair_is_the_follower_minus_the_example(tmp_path):
    # the example toes out 7 degrees, the follower the same: no fault; the example turned in 10 and the follower
    # the same 7: the follower is 17 further out, over the whole clip
    a = analyse_with(tmp_path, expected=side_doc(EXPECTED, yaw=-10.0), follower=side_doc(TAKE, yaw=7.0)).analysis
    assert {(f["measure"], f["side"], f["direction"]) for f in foot_faults(a)} == {("foot_rotation", "both", "more")}


def test_ac_foot_12_a_foot_fault_does_not_disturb_the_body_faults_it_sits_with(tmp_path):
    body = ROOT / "fixtures/input/followers/exercise/exercise_45_good_02_arms_wider-left/skeleton.json"
    plain = run(str(EXPECTED), str(body)).analysis
    both = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=side_doc(body, extra_yaw={"left": 20.0}),
                        fol_clip=body).analysis
    assert [f for f in both["faults"] if f["body_part"] != "feet"] == plain["faults"]
    assert ("foot_rotation", "left", "more") in {(f["measure"], f["side"], f["direction"]) for f in foot_faults(both)}


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-14: words and cues
# ---------------------------------------------------------------------------------------------------------------
FOOT_GENERIC = ["foot_rotation", "ankle_inversion"]
COMBOS = [(m, d, s) for m in FOOT_GENERIC for d in ("more", "less") for s in ("left", "right", "both")]


def test_ac_foot_14_every_foot_measure_direction_and_side_has_a_short_imperative_cue():
    seen = set()
    for measure, direction, side in COMBOS:
        cue, kind = cues.cue_for(measure, direction, side)
        assert 1 <= len(cue.split()) <= cues.MAX_WORDS and cue[0].isupper() and not cue.endswith(".")
        assert "\u2013" not in cue and "\u2014" not in cue and " - " not in cue and kind == "position"
        assert not any(w in cue.lower() for w in ("twist", "toe", "heel", "invert", "evert"))
        assert ("ankle" in cue.lower()) == (measure == "ankle_inversion")
        if side != "both":
            assert side in cue.split()
        seen.add(cue)
    assert len(seen) == len(COMBOS)
    for measure in FOOT_GENERIC:
        for side in ("left", "both"):
            assert cues.cue_for(measure, "more", side) != cues.cue_for(measure, "less", side)


def test_ac_foot_14_the_two_phrases_of_the_ticket_are_kept_word_for_word():
    assert cues.cue_for("foot_rotation", "less", "left")[0] == "Turn your left foot out"
    assert cues.cue_for("ankle_inversion", "more", "left")[0] == "Keep your left ankle straight"
    assert cues.cue_for("foot_rotation", "more", "both")[0] == "Turn your feet in"
    assert cues.cue_for("ankle_inversion", "less", "both")[0] == "Stop your ankles rolling in"


def test_ac_foot_14_a_cue_with_a_bad_side_or_direction_is_an_error():
    for args in (("foot_rotation", "more", "center"), ("ankle_inversion", "up", "left")):
        with pytest.raises(ValueError):
            cues.cue_for(*args)


@pytest.mark.parametrize("measure,direction,side,want", [
    ("foot_rotation", "more", "left", "left foot turned out more than the example"),
    ("foot_rotation", "more", "both", "feet turned out more than the example"),
    ("foot_rotation", "less", "right", "right foot not turned out enough"),
    ("foot_rotation", "less", "both", "feet not turned out enough"),
    ("ankle_inversion", "more", "left", "left ankle rolling out"),
    ("ankle_inversion", "more", "both", "ankles rolling out"),
    ("ankle_inversion", "less", "right", "right ankle rolling in"),
    ("ankle_inversion", "less", "both", "ankles rolling in"),
])
def test_ac_foot_14_the_plain_words(measure, direction, side, want):
    assert phrase(measure, direction, side) == want
    assert set(PHRASES) >= set(FOOT_GENERIC)


def test_ac_foot_14_the_size_qualifiers_read_cleanly():
    class F:
        measure, direction, side, threshold_deg = "foot_rotation", "less", "left", 12.0
        magnitude_deg = -14.0
    assert describe(F) == "left foot not quite turned out enough"
    F.magnitude_deg = -40.0
    assert describe(F) == "left foot nowhere near turned out enough"
    F.measure, F.direction, F.threshold_deg, F.magnitude_deg = "ankle_inversion", "more", 15.0, 50.0
    assert describe(F) == "left ankle rolling out a lot" and describe(F, qualify=False) == "left ankle rolling out"
    assert describe_timed(F) == "left ankle rolling out a lot"


def fault_record(measure, direction, side, text, timed=False):
    joint = "ankle" if side == "both" else f"{side}_ankle"
    rec = {"measure": measure, "joint": joint, "body_part": "feet", "side": side, "direction": direction, "text": text}
    if timed:
        lateral = None if side == "both" else side
        rec.update(at_s=1.9, lateral=lateral, text_timed=f"{text} at 1.9 s")
    return rec


def test_ac_foot_14_the_template_lines_pass_the_live_word_test_in_every_band():
    """The live validators (`phrasing/template.py` NAMES, RULES) cover the two measures: the template's own lines
    pass, and the opposite direction's line fails."""
    bands = ("slight", "plain", "much")
    for measure, direction, side in COMBOS:
        for band in bands:
            text = phrase(measure, direction, side, band)
            rec = fault_record(measure, direction, side, text)
            assert line_problem(rec, text) is None, (text, line_problem(rec, text))
            timed = fault_record(measure, direction, side, text, timed=True)
            assert line_problem(timed, f"{text} at 1.9 s", timed=True) is None, text
            other = "less" if direction == "more" else "more"
            wrong = phrase(measure, other, side, band)
            assert line_problem(fault_record(measure, direction, side, wrong), wrong) == "wrong direction", wrong


@pytest.mark.parametrize("measure,line,problem", [
    ("foot_rotation", "left foot turned in", "wrong direction"),
    ("foot_rotation", "left foot not turned out enough", "wrong direction"),
    ("foot_rotation", "right foot turned out", "wrong side"),
    ("foot_rotation", "left knee turned out", "does not name the body part"),
    ("foot_rotation", "left foot turned out and the shoulder drops", "adds another body part (shoulder)"),
    ("foot_rotation", "left foot turned out by 20 degrees", "adds a number"),
    ("ankle_inversion", "left ankle rolling in", "wrong direction"),
    ("ankle_inversion", "left ankle looks fine", "does not say how it differs"),
])
def test_ac_foot_14_a_model_line_that_misstates_a_foot_fault_is_refused(measure, line, problem):
    plain = {"foot_rotation": "left foot turned out", "ankle_inversion": "left ankle rolling out"}[measure]
    assert line_problem(fault_record(measure, "more", "left", plain), line) == problem


def test_ac_foot_14_the_ankle_words_in_a_model_line_read_in_and_out_by_the_measure():
    """ADR-0015 Amendment 1: `more` is the foot on its outer edge (the ankle rolling out), `less` the inner edge down
    (the ankle rolling or caving in)."""
    rec = fault_record("ankle_inversion", "more", "left", "left ankle rolling out")
    assert line_problem(rec, "your left ankle is rolling outward a little") is None
    assert line_problem(rec, "your left ankle is rolling in") == "wrong direction"
    assert line_problem(rec, "your left ankle is leaning in") == "wrong direction"
    rec_less = fault_record("ankle_inversion", "less", "left", "left ankle rolling in")
    assert line_problem(rec_less, "left ankle collapsing inward") is None
    assert line_problem(rec_less, "your left ankle is rolling out") == "wrong direction"


def test_ac_foot_14_the_live_ankle_line_is_held_to_the_direction_the_side_and_the_foot():
    """The pinned live line (timed mode): a `less` fault reads "rolling in", a `more` fault "rolling out", and the
    ankle's roll names no knee or thigh because the measure does not read them."""
    less = fault_record("ankle_inversion", "less", "left", "left ankle rolling in", timed=True)
    assert line_problem(less, "Your left ankle is rolling in at 1.9 s, nearly there.", timed=True) is None
    assert line_problem(less, "Your left ankle is rolling out at 1.9 s.", timed=True) == "wrong direction"
    assert line_problem(less, "Your left ankle is rolling in over the knee at 1.9 s.", timed=True) \
        == "adds another body part (knee)"
    more = fault_record("ankle_inversion", "more", "left", "left ankle rolling out", timed=True)
    assert line_problem(more, "Your left ankle is rolling out at 1.9 s, keep it straight.", timed=True) is None
    assert line_problem(more, "Your left ankle is rolling in at 1.9 s.", timed=True) == "wrong direction"
    assert line_problem(more, "Your left ankle is rolling out under the thigh at 1.9 s.", timed=True) \
        == "adds another body part (thigh)"


def test_ac_foot_14_the_prompt_describes_the_measures_and_knows_the_foot_words():
    from part5.phrasing import local_llm, prompt
    fault = dict(fault_record("foot_rotation", "more", "left", "left foot turned out more than the example", timed=True),
                 magnitude_deg=20.0, threshold_deg=12.0, expected_frames=[10, 40])
    system = prompt.timed_messages(fault)[0]["content"]
    assert "turned out" in system and "rolling out" in system and "The measure is: foot turned out" in system
    assert "The measure is: foot rolled onto its outer edge, the ankle rolling out" in prompt.timed_messages(
        dict(fault, measure="ankle_inversion"))[0]["content"]
    assert prompt.timed_record(dict(fault, measure="ankle_inversion"))["may_mention"] == []
    assert "The measure is:" in local_llm.messages(dict(fault, at_s=None))[0]["content"]
    assert prompt.timed_record(fault)["may_mention"] == ["hip", "knee"]


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-15: output, schema, doctor, contract
# ---------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def foot_analysis(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("feet")
    res = analyse_with(tmp, expected=side_doc(EXPECTED), follower=side_doc(TAKE, extra_yaw={"left": 20.0}),
                       score=score_block)
    return res.analysis


def test_ac_foot_15_the_document_validates_against_the_1_6_0_schema_and_the_loader(foot_analysis):
    assert SCHEMA["version"] == "1.9.0" and foot_analysis["schema_version"] == "1.9.0"
    jsonschema.Draft202012Validator(SCHEMA).validate(foot_analysis)
    validate_analysis(foot_analysis)
    assert foot_analysis["diagnostics"]["feet"]["compared"] == FOUR


def test_ac_foot_15_the_vocabulary_has_the_two_measures_after_the_body_ones():
    assert GENERIC_MEASURES[-2:] == FOOT_GENERIC
    enum = SCHEMA["$defs"]["fault"]["properties"]["measure"]["enum"]
    assert enum[-2:] == FOOT_GENERIC and "feet" in SCHEMA["$defs"]["fault"]["properties"]["body_part"]["enum"]


def test_ac_foot_15_a_1_5_0_document_still_validates(foot_analysis):
    old = copy.deepcopy(foot_analysis)
    old["schema_version"] = "1.5.0"
    old["diagnostics"].pop("feet")
    old["faults"] = [f for f in old["faults"] if f["body_part"] != "feet"]
    old["phrasing"]["faults"] = old["phrasing"]["faults"][:len(old["faults"])]
    old.pop("score"), old.pop("insights")
    jsonschema.Draft202012Validator(SCHEMA).validate(old)
    validate_analysis(old)


@pytest.mark.parametrize("edit,message", [
    (lambda f: f.update(joint="left_knee"), "joint must be 'left_ankle'"),
    (lambda f: f.update(body_part="legs"), "body_part must be 'feet'"),
    (lambda f: f.update(measure_kind="angle"), "measure_kind must be 'direction'"),
    (lambda f: f.update(side="center"), "does not go with measure"),
])
def test_ac_foot_15_validate_analysis_rejects_a_foot_fault_with_the_wrong_joint_part_kind_or_side(foot_analysis, edit, message):
    bad = copy.deepcopy(foot_analysis)
    edit(next(f for f in bad["faults"] if f["body_part"] == "feet"))
    with pytest.raises(OutputError, match=message):
        validate_analysis(bad)
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(bad))


def test_ac_foot_15_a_malformed_diagnostics_feet_is_rejected(foot_analysis):
    for edit in (lambda d: d["diagnostics"].update(feet=[]), lambda d: d["diagnostics"]["feet"].pop("compared"),
                 lambda d: d["diagnostics"]["feet"].update(compared=["left_hip"]),
                 lambda d: d["diagnostics"]["feet"].update(hidden_reason=""),
                 lambda d: d["diagnostics"]["feet"]["follower"].update(usable="all")):
        bad = copy.deepcopy(foot_analysis)
        edit(bad)
        with pytest.raises(OutputError, match="diagnostics.feet"):
            validate_analysis(bad)
        assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(bad))


def test_ac_foot_15_part5_doctor_notes_the_feet_for_part7(tmp_path, capsys, foot_analysis):
    path = write(tmp_path, foot_analysis, "analysis.json")
    assert doctor.run_doctor(type("A", (), {"file": str(path), "consumer": "part7", "json": False})()) == 0
    out = capsys.readouterr().out
    assert "accepted for part7" in out and "foot measures compared (left_foot_rotation" in out
    assert "1 foot fault (body_part feet, joint an ankle)" in out


def test_ac_foot_15_part5_doctor_says_why_the_feet_were_hidden(tmp_path, capsys):
    a = analyse_with(tmp_path, follower=side_doc(TAKE)).analysis
    path = write(tmp_path, a, "analysis.json")
    assert doctor.run_doctor(type("A", (), {"file": str(path), "consumer": "part7", "json": False})()) == 0
    assert "foot measures hidden (diagnostics.feet): no expected feet file was given" in capsys.readouterr().out


def test_ac_foot_15_doctor_accepts_a_pose3d_as_a_feet_side_input_with_a_note(tmp_path):
    r = doctor.inspect_file(WITH_FEET)
    assert r.kind.id == "pose3d" and r.exit_code == 0 and r.verdict == "accepted"
    assert any("foot points in 4 of 4 frames, people ids [0, 7]" in n for n in r.notes)
    assert any(n.startswith("not a clip: for the body pass Part 3's skeleton.json") for n in r.notes)


def test_ac_foot_15_doctor_accepts_a_pose3d_without_extra_joints_and_says_no_foot_points():
    r = doctor.inspect_file(NO_FEET)
    assert r.exit_code == 0 and any(n.startswith("no foot points (no extra_joints in any frame") for n in r.notes)


def test_ac_foot_15_the_contract_table_has_the_feet_row_checked_against_the_part_2_commit():
    row = next(r for r in contract.table_rows() if r["producer"] == "Part 2 foot points")
    assert row["checked_against"] == "Part 2 e8ac336" and row["verdict"] == "works with an option"
    assert "--expected-feet" in row["part5_role"] and "--follower-feet" in row["part5_role"]
    assert "extra_joints" in row["file"] and "Extra joints (optional)" in row["format"]
    assert "(Part 2 e8ac336)" not in row["fix"] and "diagnostics.feet" in row["fix"]
    text = (ROOT / "CONTRACT.md").read_text()
    assert "Part 2 e8ac336" in text and "### The feet side input" in text


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-16: the score
# ---------------------------------------------------------------------------------------------------------------
def test_ac_foot_16_a_take_without_a_foot_fault_scores_as_before(tmp_path, plain):
    scored = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=side_doc(TAKE), score=score_block).analysis
    assert scored["score"] == plain.analysis["score"]


def test_ac_foot_16_a_foot_fault_costs_points_like_any_fault_and_its_cue_reaches_the_timeline(tmp_path, plain,
                                                                                               foot_analysis):
    assert foot_analysis["score"]["value"] < plain.analysis["score"]["value"]
    misses = [m for w in foot_analysis["score"]["timeline"] for m in w["misses"]]
    assert any(m["measure"] == "foot_rotation" and m["cue"] == "Turn your left foot in" for m in misses)
    assert any(i["cue"] == "Turn your left foot in" for i in foot_analysis["insights"])


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-17: the command line and the API
# ---------------------------------------------------------------------------------------------------------------
def cli_args(tmp_path, *extra, expected=True, follower=True, **docs):
    args = ["analyse", "--expected", str(EXPECTED), "--follower", str(TAKE), "--out", str(tmp_path / "analysis.json")]
    if expected:
        args += ["--expected-feet", str(write(tmp_path, docs.get("e", side_doc(EXPECTED)), "e.json"))]
    if follower:
        args += ["--follower-feet", str(write(tmp_path, docs.get("f", side_doc(TAKE, extra_yaw={"left": 20.0})), "f.json"))]
    return args + list(extra)


def test_ac_foot_17_the_cli_takes_the_four_options_and_writes_the_foot_fault(tmp_path, capsys):
    assert cli.main(cli_args(tmp_path)) == 0
    out = capsys.readouterr().out
    doc = json.loads((tmp_path / "analysis.json").read_text())
    assert doc["schema_version"] == "1.9.0" and "left foot turned out" in out
    assert [f["measure"] for f in foot_faults(doc)] == ["foot_rotation"]
    assert doc["diagnostics"]["feet"]["expected"]["source"].endswith("e.json")


def test_ac_foot_17_the_person_options_pick_the_person(tmp_path, capsys):
    f = side_doc(TAKE, extra_yaw={"left": 20.0}, person=4)
    e = side_doc(EXPECTED, person=2)
    assert cli.main(cli_args(tmp_path, "--expected-feet-person", "2", "--follower-feet-person", "4", e=e, f=f)) == 0
    doc = json.loads((tmp_path / "analysis.json").read_text())
    assert doc["diagnostics"]["feet"]["expected"]["person"] == 2 and doc["diagnostics"]["feet"]["follower"]["person"] == 4
    assert len(foot_faults(doc)) == 1
    assert cli.main(cli_args(tmp_path, e=e, f=f)) == 1     # the default person 0 is in no frame
    assert "person 0 is in no frame (ids present: [2])" in capsys.readouterr().err


@pytest.mark.parametrize("name,doc,message", [
    ("not-json", "{nope", "cannot read JSON"),
    ("too-deep", "[" * 100_000 + "]" * 100_000, "cannot read JSON (nested too deeply)"),
    ("no-frames", {"frames": []}, "not a Part 2 pose3d.json"),
])
def test_ac_foot_17_an_unusable_feet_file_exits_1_with_a_plain_message_and_writes_nothing(tmp_path, capsys, name, doc, message):
    bad = tmp_path / f"{name}.json"
    bad.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    code = cli.main(cli_args(tmp_path, expected=False, follower=False) + ["--expected-feet", str(bad)])
    err = capsys.readouterr().err
    assert code == 1 and err.startswith(f"part5 analyse: {bad}: ") and message in err and "Traceback" not in err
    assert not (tmp_path / "analysis.json").exists()


def test_ac_foot_17_a_missing_feet_file_exits_1(tmp_path, capsys):
    args = cli_args(tmp_path, expected=False, follower=False) + ["--follower-feet", str(tmp_path / "nope.json")]
    assert cli.main(args) == 1 and "cannot read JSON" in capsys.readouterr().err


def test_ac_foot_17_a_file_that_matches_no_frame_exits_1(tmp_path, capsys):
    late = side_doc(TAKE)
    for fr in late["frames"]:
        fr["t_ms"] += 99000.0
    assert cli.main(cli_args(tmp_path, f=late)) == 1
    assert "no frame of the follower clip matches a frame of this file in time" in capsys.readouterr().err


def test_ac_foot_17_a_file_with_no_foot_points_exits_0_and_hides_the_measures(tmp_path):
    assert cli.main(cli_args(tmp_path, f=side_doc(TAKE, feet_present=False))) == 0
    info = json.loads((tmp_path / "analysis.json").read_text())["diagnostics"]["feet"]
    assert info["compared"] == [] and "has no extra_joints" in info["hidden_reason"]


def test_ac_foot_17_a_person_option_that_is_not_a_number_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(cli_args(tmp_path, "--follower-feet-person", "left"))
    assert e.value.code == 2


def test_ac_foot_17_the_api_passes_the_feet_through_analyse(tmp_path):
    e, f = write(tmp_path, side_doc(EXPECTED), "e.json"), write(tmp_path, side_doc(TAKE, extra_roll={"left": 25.0}), "f.json")
    a = analyse(str(EXPECTED), str(TAKE), expected_feet=str(e), follower_feet=f, expected_feet_person=0,
                follower_feet_person=0)
    assert [x["measure"] for x in foot_faults(a)] == ["ankle_inversion"]
    assert "feet" not in analyse(str(EXPECTED), str(TAKE))["diagnostics"]


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-18: labels and the evaluation
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("type_,measure", [("foot_turned_out", "foot_rotation"), ("foot_turned_in", "foot_rotation"),
                                           ("ankle_rolled_in", "ankle_inversion"), ("ankle_rolled_out", "ankle_inversion")])
def test_ac_foot_18_the_label_types_map_to_the_foot_measures(type_, measure):
    assert evaluate.LABEL_TYPE_TO_MEASURE[type_] == measure
    label = {"type": type_, "measure": measure, "body_part": "feet", "side": "left", "direction": "more"}
    assert evaluate.canonical_label(label) == (measure, "left", "more")


def test_ac_foot_18_a_foot_prediction_matches_its_label_on_measure_side_and_direction():
    label = {"type": "foot_turned_out", "side": "both", "direction": "more", "body_part": "feet", "measure": "foot_rotation"}
    pred = {"measure": "foot_rotation", "side": "left", "direction": "more"}
    assert evaluate.matches(pred, label) and not evaluate.matches(dict(pred, direction="less"), label)
    assert not evaluate.matches(dict(pred, measure="ankle_inversion"), label)
    scored = evaluate.score([{"predicted": [pred], "labels": [label], "lighting": "good", "angle": "front",
                              "correct": False}])
    assert scored["good_light"]["precision"] == 1.0 and scored["good_light"]["recall"] == 1.0


def test_ac_foot_18_labels_schema_accepts_the_foot_types_the_feet_paths_and_the_feet_body_part():
    take = {"take_id": "t", "correct": False, "expected": "a.json", "follower": "b.json",
            "expected_feet": "fixtures/input/expected-feet/x/pose3d.json", "follower_feet": "fixtures/input/f/pose3d.json",
            "faults": [{"type": "foot_turned_in", "measure": "foot_rotation", "body_part": "feet", "side": "left",
                        "direction": "less", "joints": ["left_ankle"]}]}
    doc = {"format": "simon.part5.labels.v1", "takes": [take]}
    jsonschema.Draft202012Validator(LABELS_SCHEMA).validate(doc)
    bad = copy.deepcopy(doc)
    bad["takes"][0]["faults"][0]["type"] = "foot_twisted"
    assert list(jsonschema.Draft202012Validator(LABELS_SCHEMA).iter_errors(bad))
    bad = copy.deepcopy(doc)
    bad["takes"][0]["follower_feet"] = 3
    assert list(jsonschema.Draft202012Validator(LABELS_SCHEMA).iter_errors(bad))


# ---------------------------------------------------------------------------------------------------------------
# the pair and detect, without a clip
# ---------------------------------------------------------------------------------------------------------------
def test_pair_of_is_none_without_a_feet_file_and_names_the_reason_otherwise():
    assert pair_of(load_side("expected", None, 0, FRAME_S), load_side("follower", None, 0, FRAME_S)) is None
    pair = pair_of(load_side("expected", None, 0, FRAME_S), load())
    assert pair.compared == [] and pair.hidden_reason == "no expected feet file was given"
    assert pair.diagnostics()["follower"]["usable"] == ["right_foot_rotation", "right_ankle_inversion"]
    assert pair.hidden("rep mode").hidden_reason == "rep mode" and pair.hidden("x").compared == []
    both = pair_of(load(person=7), load(person=7, label="expected"))
    assert both.compared == FOUR and both.hidden_reason is None
    nothing = pair_of(load(NO_FEET, label="expected"), load(NO_FEET))
    assert nothing.hidden_reason.count("no extra_joints") == 2


def test_detect_visits_the_foot_measures_only_when_both_dicts_carry_them():
    from part5.align import Alignment
    n = 40
    al = Alignment(path=[(i, i) for i in range(n)], exp_to_fol=np.arange(n), fol_phase=np.linspace(0, 1, n),
                   residual=0.0, measures=[])
    zero = {m: np.zeros(n) for m in MEASURES}
    exp = {**zero, "left_foot_rotation": np.zeros(n)}
    fol = {**zero, "left_foot_rotation": np.full(n, 30.0)}
    faults = detect(exp, fol, al, load_rules())
    assert [(f.measure, f.side, f.direction, f.joint, f.body_part) for f in faults] == \
        [("foot_rotation", "left", "more", "left_ankle", "feet")]
    assert detect(exp, {**zero}, al, load_rules()) == [] and detect({**zero}, fol, al, load_rules()) == []
    assert detect(zero, zero, al, load_rules()) == []


def test_the_geometry_guards_and_the_floor_are_the_documented_ones():
    from part5.measures import MIN_CROSS_SHARE, MIN_GROUND_SHARE, MIN_TOE_SPREAD
    assert (MIN_GROUND_SHARE, MIN_CROSS_SHARE, MIN_TOE_SPREAD) == (0.25, 0.25, 0.1)
    assert FOOT_MIN_CONF == 0.5 and math.isclose(MIN_SEEN_SHARE, 0.8)
    rules = load_rules()["measures"]
    # the seed 5 calibration, attempt B (progress/calibrate-feet-seed5-attempt-b.log), written by `calibrate --feet --write`,
    # kept by the re-sweep of attempt 5 (progress/calibrate-feet-seed5-attempt5.log); `max_jitter_deg` is attempt 5's
    # steadiness limit (ADR-0015 Amendment 4, tests/test_feet_steady.py)
    assert rules["foot_rotation"] == {"threshold_deg": 14.0, "max_jitter_deg": 4.0}
    assert rules["ankle_inversion"] == {"threshold_deg": 14.0, "max_jitter_deg": 4.0}


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-18 (cont.): a labelled set is run with the feet its labels name (score_report, check-5, calibration)
# ---------------------------------------------------------------------------------------------------------------
def labelled_set(tmp_path):
    write(tmp_path, side_doc(EXPECTED), "e.json")
    write(tmp_path, side_doc(TAKE, extra_yaw={"left": 20.0}), "f.json")
    base = {"lighting": "good", "angle": "45", "correct": False, "faults": [], "expected": str(EXPECTED),
            "follower": str(TAKE)}
    return {"seed": 5, "takes": [dict(base, take_id="with_feet", expected_feet="e.json", follower_feet="f.json"),
                                 dict(base, take_id="without")]}


def test_ac_foot_18_feet_kwargs_resolves_the_label_paths_against_the_base(tmp_path):
    from part5 import score_report
    take = labelled_set(tmp_path)["takes"][0]
    assert score_report.feet_kwargs(take, tmp_path) == {"expected_feet": str(tmp_path / "e.json"),
                                                        "follower_feet": str(tmp_path / "f.json")}
    assert score_report.feet_kwargs(dict(take, expected_feet=str(tmp_path / "x.json")), tmp_path)["expected_feet"] \
        == str(tmp_path / "x.json")
    assert score_report.feet_kwargs({"take_id": "t", "expected_feet": None}, tmp_path) == {}
    assert score_report.feet_kwargs({"take_id": "t"}) == {}


def test_ac_foot_18_run_set_scored_set_and_the_calibration_rows_run_a_take_with_its_feet(tmp_path):
    from part5 import score_report
    labels = labelled_set(tmp_path)
    with_feet, without = score_report.run_set(labels, base=tmp_path)
    assert with_feet[1].analysis["diagnostics"]["feet"]["compared"] == FOUR
    assert [f["measure"] for f in foot_faults(with_feet[1].analysis)] == ["foot_rotation"]
    assert "feet" not in without[1].analysis["diagnostics"]      # no label keys: analysed as before
    scores = score_report.scored_set(labels, base=tmp_path)
    assert scores["with_feet"]["value"] < scores["without"]["value"]
    rows = score_report.rows_of_set(labels, base=tmp_path)
    assert len(rows[0]["faults"]) == 1 and rows[1]["faults"] == []


def test_ac_foot_18_score_report_analyse_takes_the_feet_options(tmp_path):
    from part5 import score_report
    take = labelled_set(tmp_path)["takes"][0]
    a = score_report.analyse(str(EXPECTED), str(TAKE), **score_report.feet_kwargs(take, tmp_path))
    assert a["score"] and foot_faults(a) and a["diagnostics"]["feet"]["hidden_reason"] is None
    assert "feet" not in score_report.analyse(str(EXPECTED), str(TAKE))["diagnostics"]
