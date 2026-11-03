"""TICKET-107, AC-Q17 (ADR-0021 Amendment 2, docs/specs/quality.md "The example's visibility"): `hidden_measure_share`, the
`measures_hidden` reason, the level and `score_cap` count only the full-body measures the example shows. A measure the example
cannot show is not applicable, so it is not left out of the take; a follower who hides a joint the example shows still counts.

The regression take is staging take b5acba462f16 (moalborati/simon-part-5-fault-analysis#38), a seated routine filmed from the chest
up whose trainer marks its hips, knees and ankles unseen (`tests/fixtures/staging-b5acba462f16/`)."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest
from test_quality import EXPECTED, conf_with, still

from part5 import quality
from part5.io import JOINTS, load_clip
from part5.measures import MEASURES
from part5.pipeline import run
from part5.score_report import score_block
from part5.visibility import usable_from_conf

ROOT = Path(__file__).resolve().parent.parent
TAKE = ROOT / "tests/fixtures/staging-b5acba462f16"
LEGS = ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")
UPPER = np.array([j not in LEGS for j in JOINTS])
CHEST_UP = ["left_elbow_flexion", "left_upper_arm_out", "left_forearm_out", "right_elbow_flexion", "right_upper_arm_out",
            "right_forearm_out", "shoulder_tilt"]


@pytest.fixture(scope="module")
def staged():
    return run(str(TAKE / "expected.json"), str(TAKE / "follower.json"), score=score_block).analysis


@pytest.fixture(scope="module")
def pose():
    """One standing pose (17, 3) of Part 4's squat, as `tests/test_quality.py` reads it."""
    return load_clip(EXPECTED).positions[0].copy()


def legs_hidden(n):
    return conf_with(n, **{joint: 0.3 for joint in LEGS})


# ---------------------------------------------------------------------------------------------- the regression take
def test_the_trainer_of_the_regression_take_marks_its_legs_unseen_and_shows_seven_measures():
    doc = json.loads((TAKE / "expected.json").read_text())
    assert doc["unseen_joints"] == list(LEGS)
    shown = quality.shown_joints(load_clip(TAKE / "expected.json").conf)
    assert shown.tolist() == UPPER.tolist()
    assert quality.shown_measures(shown) == CHEST_UP


def test_the_regression_take_reads_ok_with_no_measures_hidden_and_no_cap(staged):
    """1.14.1 read it major: measures_hidden 0.6818 (15 of 22), score_cap 59. The follower hid exactly what the trainer hid."""
    q = staged["quality"]
    assert q["level"] == "ok" and q["reasons"] == [] and q["score_cap"] is None
    assert q["signals"]["hidden_measure_share"] == 0.0 and q["signals"]["unseen_joint_share"] == 0.0


def test_against_a_trainer_that_shows_its_legs_the_same_follower_is_still_major_on_them(tmp_path):
    """A follower who hides joints the trainer shows is flagged as before: the trainer's conf set to 1.0 on every joint."""
    doc = json.loads((TAKE / "expected.json").read_text())
    full = copy.deepcopy(doc)
    for frame in full["frames"]:
        frame["conf"] = {joint: 1.0 for joint in frame["conf"]}
    full["unseen_joints"] = []
    (tmp_path / "expected.json").write_text(json.dumps(full))
    q = run(str(tmp_path / "expected.json"), str(TAKE / "follower.json"), score=score_block).analysis["quality"]
    assert q["signals"]["hidden_measure_share"] == round(15 / 22, 4) and q["level"] == "major" and q["score_cap"] == 59
    hidden = next(r for r in q["reasons"] if r["code"] == "measures_hidden")
    assert hidden["words"] == "15 of 22 measures were left out because their joints were not seen in enough of the take."


# ---------------------------------------------------------------------------------------------- the rule
def test_an_example_of_unknown_visibility_holds_the_follower_to_all_22_measures_as_before(pose):
    n = 40
    got = quality.read_signals(still(pose, n, conf=legs_hidden(n)))
    hidden = [m for m in MEASURES if m not in usable_from_conf(legs_hidden(n))]
    assert len(hidden) == 15 and got.measures_shown == 22
    assert got.signals["hidden_measure_share"] == round(15 / 22, 4)


def test_a_measure_the_example_does_not_show_is_not_left_out_of_the_take(pose):
    n = 40
    got = quality.read_signals(still(pose, n, conf=legs_hidden(n)), quality.shown_joints(legs_hidden(n)))
    assert got.measures_shown == 7 and got.signals["hidden_measure_share"] == 0.0
    assert quality.assess(got)["level"] == "ok"


def test_a_follower_who_also_hides_an_arm_the_example_shows_counts_it_over_the_measures_shown(pose):
    n = 40
    follower = conf_with(n, **{joint: 0.3 for joint in (*LEGS, "left_elbow", "left_wrist", "right_elbow", "right_wrist")})
    got = quality.read_signals(still(pose, n, conf=follower), quality.shown_joints(legs_hidden(n)))
    lost = [m for m in CHEST_UP if m not in usable_from_conf(follower)]
    assert len(lost) == 6   # both arms below the shoulder; the shoulder line stays
    assert got.signals["hidden_measure_share"] == round(6 / 7, 4)
    block = quality.assess(got)
    reason = next(r for r in block["reasons"] if r["code"] == "measures_hidden")
    assert block["level"] == "major" and block["score_cap"] == 59
    assert reason["words"] == ("6 of the 7 measures the example shows were left out because their joints were not seen in enough "
                               "of the take.")


def test_an_example_that_shows_no_full_body_measure_reads_null_and_adds_no_reason(pose):
    n = 40
    face_only = np.array([j in ("nose", "left_eye", "right_eye", "left_ear", "right_ear") for j in JOINTS])
    assert quality.shown_measures(face_only) == []
    got = quality.read_signals(still(pose, n, conf=legs_hidden(n)), face_only)
    assert got.signals["hidden_measure_share"] is None
    assert "measures_hidden" not in {r["code"] for r in quality.assess(got)["reasons"]}


def test_the_heading_keeps_the_count_of_measures_shown(pose):
    n = 40
    got = quality.with_heading(quality.read_signals(still(pose, n, conf=legs_hidden(n)), UPPER), 1.0)
    assert got.measures_shown == 7 and got.signals["heading_offset_deg"] == 1.0
