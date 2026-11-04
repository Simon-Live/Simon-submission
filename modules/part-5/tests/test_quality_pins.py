"""TICKET-079, AC-Q06 to AC-Q09 and AC-Q14: the quality block through the whole pipeline (ADR-0021, docs/specs/quality.md).

- AC-Q08 (T1, pinned): every clean good-light take of seed 5 is level ok; the low-light takes (T2) are not.
- AC-Q06: with the block or without it, the document is the same beyond `quality`: score.value, grade, fault_cap, uncapped,
  capped_by and warnings are byte for byte what they were, and the block never adds a warning.
- AC-Q05 through the pipeline: a take that carries a visibility warning is major with that reason; low_match is not a reason.
- AC-Q09: the shipped degraded sample is major with a cap of 59 that is reported and not applied.
- AC-Q14: the four goldens that existed before differ from their old bytes by the block and by nothing else.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from part5 import contract, output, pipeline
from part5.output import write_analysis

ROOT = Path(__file__).resolve().parent.parent
TUNING = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
EXERCISE = {"path": "fixtures/input/expected/exercise/animation.json", "set": "exercise", "movement": "squat"}
OUT = ROOT / "fixtures/output"
SAMPLE = OUT / "analysis.quality-major.example.json"
# sha256 of the four goldens as main had them just before the block (c23dde4, the credit grade scale in): the block is all that
# the quality change added. At c8673d1, before the grade scale, they were 3a4e00a8, 3aa17c2d, 4913d1bd and 643f2b59 (first 8 digits).
# repinned 2026-11-03 for the credit's grade scale (E from 40, F under 40; the team on moalborati/simon#61):
# only score.credit.grades differs, no letter changed
BEFORE = {"analysis.example.json": "1ffe49d6050b422058d41a85aa8ea95700c253b98c6ad087bf96c1911df7caef",
          "analysis.no-faults.example.json": "42915eac4e9d9374843e0f4505dee5473e6c5253c5bd2fb42d9add46b7f62677",
          "analysis.fault-capped.example.json": "f90370f345ae397f14233985f77e61fc0456cdc854842f1ea597de5189ccd9e4",
          "analysis.double-capped.example.json": "8b78ebdb70a2db3a531af993598ac7bfbaa181d351420d3515810db6efa15256"}
SCORE_FIELDS = ("value", "grade", "fault_cap", "uncapped", "capped_by")


def take_ref(take):
    return {"path": take["follower"], "take_id": take["take_id"]}


def analyse(take, expected=None):
    return contract.golden_run(expected or {"path": take["expected"], "set": take["set"], "movement": take["movement"]},
                               take_ref(take)).analysis


def seed5(lighting):
    return [t for t in TUNING["takes"] if t["lighting"] == lighting and t["variant"] == "clean"]


def hidden(*parts):
    """(take, ref) for the squat's correct front take with every joint whose name holds one of `parts` at Part 2's unseen mark
    (`conf` 0.3) in every frame; no part means every joint."""
    take = next(t for t in seed5("good") if t["take_id"] == "exercise_front_good_00_correct")
    doc = json.loads((ROOT / take["follower"]).read_text())
    for frame in doc["frames"]:
        frame["conf"] = {j: (0.3 if not parts or any(p in j for p in parts) else 1.0) for j in doc["joints"]}
    return take, {"path": take["follower"], "take_id": take["take_id"], "doc": doc}


def run_hidden(*parts):
    take, ref = hidden(*parts)
    return contract.golden_run({"path": take["expected"], "set": take["set"], "movement": take["movement"]}, ref).analysis


# ---------------------------------------------------------------------------------------------- AC-Q08 and T2
def test_every_clean_good_light_take_of_seed_5_is_ok():
    takes = seed5("good")
    assert len(takes) == 78
    bad = {t["take_id"]: (a["quality"]["level"], [r["code"] for r in a["quality"]["reasons"]], a["quality"]["signals"])
           for t in takes if (a := analyse(t))["quality"]["level"] != "ok"}
    assert bad == {}


def test_every_low_light_take_of_seed_5_is_degraded_and_none_is_ok_or_major():
    """T2: the jitter of the planted low-light noise is past the degraded limit and under the major one on all 78."""
    takes = seed5("low")
    assert len(takes) == 78
    levels = {t["take_id"]: (a := analyse(t))["quality"]["level"] for t in takes}
    assert set(levels.values()) == {"degraded"}, {k: v for k, v in levels.items() if v != "degraded"}
    # position_jitter is the reason; from 1.14.0 a low-light take past 5 degrees also reads heading_offset (TICKET-086)
    assert all([r["code"] for r in analyse(t)["quality"]["reasons"] if r["code"] != "heading_offset"] == ["position_jitter"]
               for t in takes[:6])


def test_a_good_light_take_reads_its_jitter_under_the_degraded_limit_with_a_margin():
    top = max(analyse(t)["quality"]["signals"]["position_jitter_mm"] for t in seed5("good"))
    bottom = min(analyse(t)["quality"]["signals"]["position_jitter_mm"] for t in seed5("low"))
    assert top < 21.0 - 3 and 21.0 + 4 < bottom, (top, bottom)


# ---------------------------------------------------------------------------------------------- AC-Q06: reported only
def without_block(monkeypatch, take, expected=None):
    monkeypatch.setattr(pipeline, "_quality_block", lambda ctx: None)
    try:
        return analyse(take, expected)
    finally:
        monkeypatch.undo()


def picked():
    """A correct take, a faulted one, a double fault, a low-light one and a dance take, all of seed 5."""
    good = seed5("good")
    return [next(t for t in good if "exercise_front" in t["take_id"] and t["take_id"].endswith("00_correct")),
            next(t for t in good if "exercise_front" in t["take_id"] and "foot_out" in t["take_id"]),
            next(t for t in good if t["take_id"].startswith("exercise_front_good_08")),
            next(t for t in seed5("low") if "exercise_side" in t["take_id"]),
            next(t for t in good if t["take_id"].startswith("dance_side_good_11"))]


@pytest.mark.parametrize("take", picked(), ids=lambda t: t["take_id"])
def test_the_document_is_the_same_with_the_block_taken_out(monkeypatch, take):
    with_block = analyse(take)
    bare = without_block(monkeypatch, take)
    assert "quality" in with_block and "quality" not in bare
    assert {k: v for k, v in with_block.items() if k != "quality"} == bare
    assert json.dumps({k: v for k, v in with_block.items() if k != "quality"}) == json.dumps(bare)
    for field in SCORE_FIELDS:
        assert with_block["score"].get(field) == bare["score"].get(field)
    assert with_block.get("warnings") == bare.get("warnings") and with_block["status"] == bare["status"]


def test_the_block_never_adds_a_warning_even_when_it_is_major(monkeypatch):
    degraded = json.loads((ROOT / "fixtures/input/quality/exercise_front_dark_00/skeleton.json").read_text())
    ref = {"path": "fixtures/input/quality/exercise_front_dark_00/skeleton.json", "take_id": "dark", "doc": degraded}
    result = contract.golden_run(EXERCISE, ref).analysis
    assert result["quality"]["level"] == "major" and result["quality"]["score_cap"] == 59
    assert "warnings" not in result and "capped_by" not in result["score"] and "match" not in result
    assert result["score"]["value"] > 59 and result["status"]["text"] == "Compared with the expected movement."
    monkeypatch.setattr(pipeline, "_quality_block", lambda ctx: None)
    bare = contract.golden_run(EXERCISE, {**ref, "doc": copy.deepcopy(degraded)}).analysis
    assert {k: v for k, v in result.items() if k != "quality"} == bare


# ---------------------------------------------------------------------------------------------- AC-Q05 through the pipeline
def test_legs_and_arms_out_of_frame_carry_the_moving_part_warning_and_the_block_is_major_with_that_reason_first():
    got = run_hidden("knee", "ankle", "elbow", "wrist")
    codes = [w["code"] for w in got["warnings"]]
    assert codes == ["moving_part_out_of_frame"]
    block = got["quality"]
    assert block["level"] == "major" and block["score_cap"] == 59
    assert block["reasons"][0] == {"code": "moving_part_out_of_frame", "value": None, "threshold": None,
                                   "words": "The part of the body the example moves was mostly out of frame."}
    assert got["score"]["value"] <= 59 and got["score"]["capped_by"] == codes   # Part 5's own warning cap, not the block's
    output.validate_analysis(got)


def test_nothing_in_view_is_major_with_both_warnings_as_reasons():
    got = run_hidden()
    codes = [w["code"] for w in got["warnings"]]
    assert codes == ["not_enough_visible", "no_usable_measures"]
    assert [r["code"] for r in got["quality"]["reasons"]][:2] == codes
    assert got["quality"]["level"] == "major" and got["quality"]["score_cap"] == 59
    output.validate_analysis(got)


def test_a_take_with_a_low_match_and_a_visibility_warning_lists_the_visibility_reason_and_not_the_match():
    got = run_hidden("nose", "eye", "ear", "elbow", "wrist", "knee", "ankle", "hip")
    codes = [w["code"] for w in got["warnings"]]
    assert codes == ["low_match", "not_enough_visible"]
    assert "low_match" not in {r["code"] for r in got["quality"]["reasons"]}
    assert got["quality"]["reasons"][0]["code"] == "not_enough_visible" and got["quality"]["level"] == "major"


def test_legs_out_of_frame_alone_carry_no_warning_and_the_score_is_left_alone():
    """The squat moves its arms too, so the camera still sees what is compared: no warning and the score as it was. The example has
    no conf, so its visibility is unknown, every joint counts and 4 of 17 joints is past the major limit of 0.2: the block says major,
    reports the cap, and applies none of it (the reported limitation of spec 'The example's visibility')."""
    got = run_hidden("knee", "ankle")
    assert "warnings" not in got and got["score"]["value"] == 100 and "capped_by" not in got["score"]
    assert got["quality"]["level"] == "major" and got["quality"]["score_cap"] == 59
    assert [r["code"] for r in got["quality"]["reasons"]] == ["joints_unseen", "measures_hidden"]
    assert got["quality"]["reasons"][0]["value"] == round(4 / 17, 4)


def test_a_low_match_take_is_not_a_quality_reason():
    """A dance take against the squat is another movement: low_match, F, and a block that reads the file and not the match.
    From 1.14.0 the heading offset (TICKET-086) reads the aligned pair, so it is the one reason such a take may carry."""
    take = next(t for t in seed5("good") if t["take_id"].startswith("dance_front_good_00"))
    got = analyse(take, EXERCISE)
    assert [w["code"] for w in got["warnings"]] == ["low_match"] and got["match"]["quality"] == "low"
    turned = got["quality"]["signals"]["heading_offset_deg"] >= 5.0
    assert [r["code"] for r in got["quality"]["reasons"]] == (["heading_offset"] if turned else [])
    assert got["quality"]["level"] == ("degraded" if turned else "ok") and got["quality"]["score_cap"] is None
    assert got["score"]["value"] <= 59   # capped by Part 5's warning, not by the block


# ---------------------------------------------------------------------------------------------- AC-Q09: the shipped sample
def test_the_shipped_sample_is_major_with_a_reported_cap_of_59_and_a_score_it_leaves_alone():
    doc = json.loads(SAMPLE.read_text())
    block = doc["quality"]
    assert block["level"] == "major" and block["score_cap"] == 59 and block["version"] == "simon.quality.v1"
    assert [r["code"] for r in block["reasons"]][0] == "joints_unseen"
    assert block["reasons"][0]["value"] >= block["reasons"][0]["threshold"] == 0.2
    assert doc["score"]["value"] > 59 and "warnings" not in doc and "capped_by" not in doc["score"]
    assert doc["faults"] == [] and doc["schema_version"] == "1.14.0"
    output.validate_analysis(doc)


def test_the_shipped_sample_is_what_the_pipeline_writes_from_its_input(tmp_path):
    doc = json.loads(SAMPLE.read_text())
    refs = [dict(doc[k], doc=json.loads((ROOT / doc[k]["path"]).read_text())) for k in ("expected", "follower")]
    write_analysis(tmp_path / "a.json", contract.golden_run(*refs).analysis)
    assert (tmp_path / "a.json").read_bytes() == SAMPLE.read_bytes()


def test_the_sample_input_is_the_script_s_output():
    import subprocess
    import sys
    done = subprocess.run([sys.executable, str(ROOT / "scripts/make_quality_sample.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


# ---------------------------------------------------------------------------------------------- AC-Q14: the goldens
@pytest.mark.parametrize("name", BEFORE)
def test_a_golden_differs_from_its_old_bytes_by_the_block_alone(name):
    doc = json.loads((OUT / name).read_text())
    assert "quality" in doc
    keys = list(doc)
    assert keys.index("faults") < keys.index("quality") < keys.index("diagnostics")
    assert doc["schema_version"] == "1.14.0"   # 1.14.0 (TICKET-080, TICKET-084) changed nothing else in these goldens
    was = {k: ("1.13.0" if k == "schema_version" else v) for k, v in doc.items() if k != "quality"}
    old = (json.dumps(was, indent=2, allow_nan=False) + "\n").encode()
    assert hashlib.sha256(old).hexdigest() == BEFORE[name]


def test_the_five_analysis_goldens_carry_the_block_and_the_squat_ones_read_ok():
    levels = {p.name: json.loads(p.read_text())["quality"]["level"] for p in sorted(OUT.glob("analysis*.json"))}
    assert levels["analysis.quality-major.example.json"] == "major"
    assert levels["analysis.example.json"] == levels["analysis.no-faults.example.json"] == "ok"
    assert levels["analysis.fault-capped.example.json"] == "ok"
    assert len(levels) == 5 and "analysis.double-capped.example.json" in levels


def test_the_real_lateral_raise_reads_major_because_its_trainer_says_nothing_about_what_it_sees():
    """The reported limitation (spec, "The example's visibility"). The committed real follower was filmed from the waist up: its legs
    are at the unseen mark, 4 of 17 joints. The trainer is a Part 4 animation with no `conf`, so its visibility is unknown, every
    joint counts, and 4 of 17 is past the major limit of 0.2. Nothing is tuned for it. A trainer that carried its own conf would
    excuse its legs (the tests below). Until 1.14.1 `hidden_measure_share` did not read the example, so with the trainer's
    visibility this take read `degraded` on measures_hidden (0.4545) and pexels-8836968 `major` (0.8636) (review R2 of 1.13.0).
    From 1.14.2 (TICKET-107) the share counts only the measures the trainer shows: this take reads `ok` (0.0) and pexels-8836968,
    which hides measures the trainer shows, stays `major` (9 of 12, 0.75), both pinned in tests/test_api_expected_visibility.py."""
    doc = json.loads((OUT / "analysis.double-capped.example.json").read_text())
    block = doc["quality"]
    assert not any("conf" in frame for frame in json.loads((ROOT / doc["expected"]["path"]).read_text())["frames"])
    assert block["signals"]["unseen_joint_share"] == round(4 / 17, 4) and block["level"] == "major" and block["score_cap"] == 59
    assert [r["code"] for r in block["reasons"]] == ["joints_unseen", "measures_hidden"]
    assert block["signals"]["position_jitter_mm"] < 1.0   # Part 3's skeleton is smooth: jitter says little on a real file
    assert "warnings" not in doc and doc["score"]["value"] == 79   # reported only: the score is the one it had


# ---------------------------------------------------------------------------------------------- AC-Q15: the example's visibility
def example_with_unseen(tmp_path, name, parts):
    """The squat example with every joint whose name holds one of `parts` at the unseen mark in every frame, as a trainer who
    did not show them would be written (Part 4's animation schema allows a per-frame `conf`)."""
    doc = json.loads((ROOT / EXERCISE["path"]).read_text())
    for frame in doc["frames"]:
        frame["conf"] = {j: (0.3 if any(p in j for p in parts) else 1.0) for j in doc["joints"]}
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(doc))
    return path


def test_a_waist_up_example_excuses_the_legs_and_an_unknown_one_does_not(tmp_path):
    _, ref = hidden("knee", "ankle")
    unknown = contract.golden_run(EXERCISE, ref).analysis["quality"]
    waist_up = {"path": str(example_with_unseen(tmp_path, "waist-up", ("knee", "ankle"))), "set": "exercise", "movement": "squat"}
    excused = contract.golden_run(waist_up, ref).analysis["quality"]
    assert unknown["signals"]["unseen_joint_share"] == round(4 / 17, 4) and unknown["level"] == "major"
    assert unknown["reasons"][0]["code"] == "joints_unseen"
    assert excused["signals"]["unseen_joint_share"] == 0.0 and "joints_unseen" not in {r["code"] for r in excused["reasons"]}


def test_expected_visibility_reads_the_same_way_as_the_examples_own_conf(tmp_path):
    _, ref = hidden("knee", "ankle")
    visibility = example_with_unseen(tmp_path, "visibility", ("knee", "ankle"))
    got = pipeline.run(EXERCISE, ref, expected_visibility=str(visibility)).analysis["quality"]
    assert got["signals"]["unseen_joint_share"] == 0.0 and "joints_unseen" not in {r["code"] for r in got["reasons"]}


def test_a_follower_is_still_held_to_a_joint_the_example_shows(tmp_path):
    """The example does not show the face, elbows or wrists (9 joints); it shows 8. The follower loses its legs, 4 of those 8: the
    face and arms being absent from the example excuses nothing the follower lost."""
    _, ref = hidden("knee", "ankle")
    arms_out = {"path": str(example_with_unseen(tmp_path, "arms-out", ("nose", "eye", "ear", "elbow", "wrist"))),
                "set": "exercise", "movement": "squat"}
    got = contract.golden_run(arms_out, ref).analysis["quality"]
    assert got["signals"]["unseen_joint_share"] == 0.5 and got["level"] == "major"
