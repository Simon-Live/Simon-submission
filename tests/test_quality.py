"""TICKET-079, AC-Q02 to AC-Q05: each signal, each reason, the level, the cap, the null signals and the thresholds file
(ADR-0021, docs/specs/quality.md). The validator (AC-Q11) is tests/test_quality_validate.py."""
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from part5 import detect, output, quality
from part5.io import JOINTS, Clip, load_clip
from part5.measures import MEASURES
from part5.score import WARNING_CAP
from part5.visibility import usable_from_conf

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
J = {name: i for i, name in enumerate(JOINTS)}
FACE = ("nose", "left_eye", "right_eye", "left_ear", "right_ear")


@pytest.fixture(scope="module")
def pose():
    """One standing pose (17, 3) of Part 4's squat, hip midpoint at the origin."""
    return load_clip(EXPECTED).positions[0].copy()


def clip_of(positions, *, conf=None, mask=None, interpolated=None):
    n = len(positions)
    ok = np.ones((n, len(JOINTS)), bool) if mask is None else mask
    return Clip("simon.animation.v1", 30.0, np.arange(n) / 30.0, np.asarray(positions, float), ok,
                np.zeros(n, bool) if interpolated is None else interpolated, {}, conf)


def still(pose, n=60, **kw):
    return clip_of(np.repeat(pose[None], n, axis=0), **kw)


def conf_with(n, **marks):
    """(n, 17) conf of 1.0 with `joint=value` (or a tuple of joints via the key `face`) set."""
    conf = np.ones((n, len(JOINTS)))
    for name, value in marks.items():
        for joint in (FACE if name == "face" else (name,)):
            conf[:, J[joint]] = value
    return conf


# ---------------------------------------------------------------------------------------------- AC-Q02: the signals
def test_a_still_body_reads_a_measured_zero_jitter_and_names_no_joint(pose):
    got = quality.read_signals(still(pose))
    assert got.signals["position_jitter_mm"] == 0.0 and "position_jitter_mm" not in got.worst
    assert got.signals["missing_joint_share"] == 0.0 and got.signals["missing_frame_share"] == 0.0


def test_a_steady_movement_is_not_jitter(pose):
    """The step series removes a movement at constant speed: only the change of the step is jitter."""
    n = 60
    drift = np.repeat(pose[None], n, axis=0) + (np.arange(n) * 0.01)[:, None, None] * np.array([1.0, 0.0, 0.0])
    assert quality.read_signals(clip_of(drift)).signals["position_jitter_mm"] == 0.0


def test_a_shake_of_5_mm_reads_20_mm_a_frame(pose):
    """x alternates by +-5 mm: each step is +-10 mm, and the step changes by 20 mm every frame."""
    n = 60
    shake = np.repeat(pose[None], n, axis=0) + (0.005 * (-1.0) ** np.arange(n))[:, None, None] * np.array([1.0, 0.0, 0.0])
    got = quality.read_signals(clip_of(shake))
    assert got.signals["position_jitter_mm"] == 20.0
    assert got.worst["position_jitter_mm"] in JOINTS


def test_the_axes_join_as_a_norm(pose):
    n = 60
    swing = (0.005 * (-1.0) ** np.arange(n))[:, None, None]
    shake = np.repeat(pose[None], n, axis=0) + swing * np.array([3.0, 4.0, 0.0])
    assert quality.read_signals(clip_of(shake)).signals["position_jitter_mm"] == 100.0   # hypot(60, 80)


def test_one_wild_joint_does_not_decide_the_median(pose):
    n = 60
    positions = np.repeat(pose[None], n, axis=0)
    positions[:, J["left_wrist"], 0] += 0.02 * (-1.0) ** np.arange(n)
    got = quality.read_signals(clip_of(positions))
    assert got.signals["position_jitter_mm"] == 0.0
    assert got.worst["position_jitter_mm"] == "left_wrist"   # still named when asked who shakes most


def test_a_joint_the_clip_does_not_trust_is_left_out_of_the_jitter(pose):
    n = 60
    positions = np.repeat(pose[None], n, axis=0)
    positions[:, :, 0] += (0.005 * (-1.0) ** np.arange(n))[:, None]
    mask = np.ones((n, len(JOINTS)), bool)
    mask[:, [J[j] for j in JOINTS if j != "nose"]] = False   # only the nose is trusted
    assert quality.read_signals(clip_of(positions, mask=mask)).signals["position_jitter_mm"] == 20.0
    assert quality.read_signals(clip_of(positions, mask=np.zeros_like(mask))).signals["position_jitter_mm"] is None


def test_too_few_frames_to_judge_the_jitter_is_null_not_zero(pose):
    assert quality.read_signals(still(pose, n=4)).signals["position_jitter_mm"] is None
    assert quality.read_signals(still(pose, n=1)).signals["position_jitter_mm"] is None


def test_unseen_share_counts_the_unseen_mark_as_adr_0011_does(pose):
    """The face (nose, both eyes, both ears) at 0.3 in every frame: 5 of 17 readings. A single knee at 0.3 is a side view's far
    side, not an unseen joint, because its counterpart is seen."""
    n = 40
    assert quality.read_signals(still(pose, n, conf=conf_with(n, face=0.3))).signals["unseen_joint_share"] == round(5 / 17, 4)
    assert quality.read_signals(still(pose, n, conf=conf_with(n, left_knee=0.3))).signals["unseen_joint_share"] == 0.0
    both = conf_with(n, left_knee=0.3, right_knee=0.3)
    got = quality.read_signals(still(pose, n, conf=both))
    assert got.signals["unseen_joint_share"] == round(2 / 17, 4) and got.worst["unseen_joint_share"] in ("left_knee", "right_knee")


def test_a_joint_at_any_other_confidence_is_seen(pose):
    n = 40
    assert quality.read_signals(still(pose, n, conf=conf_with(n, face=0.31))).signals["unseen_joint_share"] == 0.0
    assert quality.read_signals(still(pose, n, conf=conf_with(n, face=1.0))).signals["unseen_joint_share"] == 0.0


def test_missing_share_counts_null_joints_and_conf_under_the_cutoff(pose):
    n = 100
    mask = np.ones((n, len(JOINTS)), bool)
    mask[:10, J["left_wrist"]] = False
    got = quality.read_signals(still(pose, n, mask=mask))
    assert got.signals["missing_joint_share"] == round(10 / (17 * n), 4)
    assert got.worst["missing_joint_share"] == "left_wrist"


def test_a_joint_at_exactly_the_unseen_mark_is_not_missing(pose):
    """conf 0.3 is seen as missing-or-not by the loader's cutoff (`conf >= 0.3` is usable): it is unseen, not missing."""
    n = 40
    got = quality.read_signals(clip_of(np.repeat(pose[None], n, axis=0), conf=conf_with(n, face=0.3)))
    assert got.signals["missing_joint_share"] == 0.0 and got.signals["unseen_joint_share"] > 0


def test_lost_frames_are_the_filled_ones_and_the_ones_with_half_the_joints_gone(pose):
    n = 50
    filled = np.zeros(n, bool)
    filled[:5] = True
    mask = np.ones((n, len(JOINTS)), bool)
    mask[10:13, :9] = False      # nine joints gone: 8 usable, at most half
    mask[20:22, :8] = False      # eight joints gone: 9 usable, not lost
    got = quality.read_signals(still(pose, n, mask=mask, interpolated=filled))
    assert got.signals["missing_frame_share"] == round((5 + 3) / n, 4)


def test_hidden_measure_share_is_the_followers_own_adr_0011_reading(pose):
    n = 40
    conf = conf_with(n, left_elbow=0.3, right_elbow=0.3, left_wrist=0.3, right_wrist=0.3)
    hidden = [m for m in MEASURES if m not in usable_from_conf(conf)]
    assert hidden, "the arms hide at least one measure"
    got = quality.read_signals(still(pose, n, conf=conf))
    assert got.signals["hidden_measure_share"] == round(len(hidden) / len(MEASURES), 4)
    assert quality.read_signals(still(pose, n, conf=conf_with(n))).signals["hidden_measure_share"] == 0.0


def test_a_file_with_no_conf_reads_null_for_the_two_signals_that_need_it_and_not_zero(pose):
    got = quality.read_signals(still(pose))
    assert got.signals["unseen_joint_share"] is None and got.signals["hidden_measure_share"] is None
    assert got.signals["missing_joint_share"] == 0.0   # a measured zero, not null


def test_every_signal_name_is_the_schemas(pose):
    assert tuple(quality.read_signals(still(pose)).signals) == output.QUALITY_SIGNALS


def test_the_readings_are_rounded_the_way_the_document_shows_them(pose):
    n = 40
    got = quality.read_signals(still(pose, n, conf=conf_with(n, face=0.3)))
    assert got.signals["unseen_joint_share"] == 0.2941 and got.signals["position_jitter_mm"] == 0.0


# ---------------------------------------------------------------------------------------------- AC-Q15: the example's visibility
LEGS = ("left_knee", "right_knee", "left_ankle", "right_ankle")


def conf_of(n, joints, value=0.3):
    conf = np.ones((n, len(JOINTS)))
    for joint in joints:
        conf[:, J[joint]] = value
    return conf


def test_an_example_of_unknown_visibility_counts_every_joint_and_fails_closed():
    """No conf anywhere: nothing is excused, and the follower's own set is never borrowed for it."""
    assert quality.shown_joints().all() and quality.shown_joints(None, None).all()
    assert quality.shown_joints(None).sum() == len(JOINTS)


def test_the_example_shows_a_joint_it_sees_in_at_least_half_of_its_frames_strictly():
    n = 40
    conf = np.ones((n, len(JOINTS)))
    conf[:, J["nose"]] = 0.3                      # never seen
    conf[: n // 2, J["left_wrist"]] = 0.3         # unseen in exactly half the frames: seen in half, shown
    conf[: n // 2 + 1, J["right_wrist"]] = 0.3    # unseen in more than half: not shown
    conf[:, J["left_knee"]] = 0.3                 # only one knee at 0.3: strict reading, the example does not see it
    shown = quality.shown_joints(conf)
    assert not shown[J["nose"]] and shown[J["left_wrist"]] and not shown[J["right_wrist"]] and not shown[J["left_knee"]]
    assert shown[J["right_knee"]] and shown.sum() == len(JOINTS) - 3


def test_a_joint_must_be_shown_by_every_conf_that_is_known():
    n = 20
    legs, arms = conf_of(n, LEGS), conf_of(n, ("left_wrist", "right_wrist"))
    shown = quality.shown_joints(legs, None, arms)
    assert not shown[[J[j] for j in (*LEGS, "left_wrist", "right_wrist")]].any() and shown.sum() == len(JOINTS) - 6


def test_the_follower_is_held_to_the_example_s_joints_only():
    """A waist-up example shows 13 joints; a follower that loses 2 of them reads 2 of 13, not 2 of 17."""
    n = 40
    example = conf_of(n, LEGS)
    shown = quality.shown_joints(example)
    assert shown.sum() == 13
    follower = still_pose_clip(n, conf_of(n, ("left_wrist", "right_wrist")))
    got = quality.read_signals(follower, shown)
    assert got.signals["unseen_joint_share"] == round(2 / 13, 4) and got.worst["unseen_joint_share"] in ("left_wrist", "right_wrist")


def test_legs_the_example_does_not_show_are_excused_and_legs_it_shows_are_not():
    n = 40
    follower = still_pose_clip(n, conf_of(n, LEGS))
    assert quality.read_signals(follower, quality.shown_joints(conf_of(n, LEGS))).signals["unseen_joint_share"] == 0.0
    assert quality.read_signals(follower, quality.shown_joints(conf_of(n, ()))).signals["unseen_joint_share"] == round(4 / 17, 4)
    assert quality.read_signals(follower, quality.shown_joints()).signals["unseen_joint_share"] == round(4 / 17, 4)
    assert quality.read_signals(follower).signals["unseen_joint_share"] == round(4 / 17, 4)   # no `shown`: every joint counts


def test_an_example_that_shows_no_joint_makes_the_signal_null_not_zero():
    n = 20
    nothing = quality.shown_joints(conf_of(n, JOINTS))
    assert not nothing.any()
    assert quality.read_signals(still_pose_clip(n, conf_of(n, LEGS)), nothing).signals["unseen_joint_share"] is None


def test_only_the_unseen_share_reads_the_example_and_no_limit_moved():
    n = 40
    follower = still_pose_clip(n, conf_of(n, ("left_wrist", "right_wrist")))
    wide, narrow = quality.read_signals(follower), quality.read_signals(follower, quality.shown_joints(conf_of(n, LEGS)))
    for name in output.QUALITY_SIGNALS:
        if name != "unseen_joint_share":
            assert wide.signals[name] == narrow.signals[name], name
    assert quality.load_thresholds()["unseen_joint_share"] == (0.1, 0.2) == quality.load_thresholds()["missing_joint_share"]


def still_pose_clip(n, conf):
    return still(load_clip(EXPECTED).positions[0].copy(), n, conf=conf)


# ---------------------------------------------------------------------------------------------- AC-Q03 and AC-Q04: reasons and level
LIMITS = {"unseen_joint_share": (0.1, 0.2), "missing_joint_share": (0.1, 0.2), "missing_frame_share": (0.1, 0.2),
          "hidden_measure_share": (0.25, 0.5), "position_jitter_mm": (21.0, 42.0), "heading_offset_deg": (5.0, None)}   # the heading is degraded only (TICKET-086)
CLEAN = {"unseen_joint_share": None, "missing_joint_share": 0.0, "missing_frame_share": 0.0, "hidden_measure_share": None,
         "position_jitter_mm": 12.0, "heading_offset_deg": 1.0}


def block(worst=None, warnings=(), **signals):
    return quality.assess(quality.Readings({**CLEAN, **signals}, worst or {}), warnings, LIMITS)


def test_a_take_below_every_limit_is_ok_with_no_reason_and_no_cap():
    got = block()
    assert got["level"] == "ok" and got["reasons"] == [] and got["score_cap"] is None
    assert got["version"] == "simon.quality.v1" and got["signals"] == CLEAN


def test_the_degraded_limit_makes_a_degraded_take_with_its_reading_and_limit_and_no_cap():
    got = block({"position_jitter_mm": "left_wrist"}, position_jitter_mm=25.0)
    assert got["level"] == "degraded" and got["score_cap"] is None
    assert got["reasons"] == [{"code": "position_jitter", "words": "Joint positions shook by about 25 mm from one frame to the "
                               "next, most at the left wrist.", "value": 25.0, "threshold": 21.0, "joint": "left_wrist"}]


def test_the_major_limit_makes_a_major_take_capped_at_the_warning_cap_and_reports_the_higher_limit():
    got = block({"position_jitter_mm": "nose"}, position_jitter_mm=50.0)
    assert got["level"] == "major" and got["score_cap"] == 59 == WARNING_CAP
    assert got["reasons"][0]["value"] == 50.0 and got["reasons"][0]["threshold"] == 42.0


@pytest.mark.parametrize("signal,limit_index,level", [
    ("unseen_joint_share", 0, "degraded"), ("unseen_joint_share", 1, "major"), ("missing_joint_share", 0, "degraded"),
    ("missing_joint_share", 1, "major"), ("missing_frame_share", 0, "degraded"), ("missing_frame_share", 1, "major"),
    ("hidden_measure_share", 0, "degraded"), ("hidden_measure_share", 1, "major"), ("position_jitter_mm", 0, "degraded"),
    ("position_jitter_mm", 1, "major"), ("heading_offset_deg", 0, "degraded")])
def test_a_signal_exactly_at_a_limit_reaches_it_and_one_hair_under_does_not(signal, limit_index, level):
    limit = LIMITS[signal][limit_index]
    at = block(**{signal: limit})
    assert at["level"] == level and at["reasons"][-1]["threshold"] == limit and at["reasons"][-1]["value"] == limit
    under = block(**{signal: round(limit - 0.0001, 4)})
    assert under["level"] == ("ok" if limit_index == 0 else "degraded")


@pytest.mark.parametrize("signal,code", [
    ("unseen_joint_share", "joints_unseen"), ("missing_joint_share", "joints_missing"), ("missing_frame_share", "frames_missing"),
    ("hidden_measure_share", "measures_hidden"), ("position_jitter_mm", "position_jitter"),
    ("heading_offset_deg", "heading_offset")])
def test_each_signal_has_its_reason_code(signal, code):
    got = block(**{signal: max(limit for limit in LIMITS[signal] if limit is not None)})
    assert [r["code"] for r in got["reasons"]] == [code]


def test_a_reason_about_a_joint_carries_the_joint_and_the_others_do_not():
    got = block({"unseen_joint_share": "nose", "missing_joint_share": "left_wrist", "position_jitter_mm": "right_knee"},
                unseen_joint_share=0.3, missing_joint_share=0.15, missing_frame_share=0.15, hidden_measure_share=0.3,
                position_jitter_mm=30.0)
    by_code = {r["code"]: r for r in got["reasons"]}
    assert by_code["joints_unseen"]["joint"] == "nose" and by_code["joints_missing"]["joint"] == "left_wrist"
    assert by_code["position_jitter"]["joint"] == "right_knee"
    assert "joint" not in by_code["frames_missing"] and "joint" not in by_code["measures_hidden"]
    assert by_code["measures_hidden"]["words"].startswith("7 of 22 measures were left out")   # round(0.3 * 22)


def test_the_reasons_come_in_the_fixed_order_and_the_level_is_the_worst():
    got = block({"unseen_joint_share": "nose", "position_jitter_mm": "nose"}, position_jitter_mm=22.0, unseen_joint_share=0.3,
                missing_frame_share=0.12)
    assert [r["code"] for r in got["reasons"]] == ["joints_unseen", "frames_missing", "position_jitter"]
    assert got["level"] == "major"   # unseen is past its major limit, the jitter only past its degraded one


def test_the_words_make_the_numbers_plain_and_name_no_cause():
    got = block({"unseen_joint_share": "nose"}, unseen_joint_share=0.2941, missing_frame_share=0.1234)
    words = {r["code"]: r["words"] for r in got["reasons"]}
    assert words["joints_unseen"] == "29 percent of the joint readings were outside the picture, most often the nose."
    assert words["frames_missing"] == "12 percent of the frames were filled in or had too few joints to use."
    for text in words.values():
        assert not any(w in text.lower() for w in ("light", "dark", "occlu", "lens"))


# ---------------------------------------------------------------------------------------------- AC-Q05: the warnings
@pytest.mark.parametrize("code", output.QUALITY_WARNING_CODES)
def test_a_visibility_warning_is_a_major_reason_with_no_number(code):
    got = block(warnings={code})
    assert got["level"] == "major" and got["score_cap"] == 59
    assert got["reasons"] == [{"code": code, "words": quality.WARNING_WORDS[code], "value": None, "threshold": None}]


def test_the_warning_reasons_come_first_and_the_signals_follow():
    got = block({"position_jitter_mm": "nose"}, warnings=["moving_part_out_of_frame", "not_enough_visible"], position_jitter_mm=25.0)
    assert [r["code"] for r in got["reasons"]] == ["not_enough_visible", "moving_part_out_of_frame", "position_jitter"]


def test_low_match_is_not_a_reason_and_leaves_the_level_to_the_signals():
    assert block(warnings={"low_match"})["level"] == "ok" and block(warnings={"low_match"})["reasons"] == []
    assert block(warnings={"low_match"}, position_jitter_mm=25.0)["level"] == "degraded"
    assert block(warnings={"no_person"})["level"] == "ok"


def test_every_warning_reason_is_one_plain_sentence():
    assert set(quality.WARNING_WORDS) == set(output.QUALITY_WARNING_CODES)
    for text in quality.WARNING_WORDS.values():
        assert text.endswith(".") and text.count(".") == 1 and len(text.split()) <= 16


# ---------------------------------------------------------------------------------------------- the block validates
def test_every_block_assess_makes_passes_the_validator():
    doc = json.loads((ROOT / "fixtures/output/analysis.no-faults.example.json").read_text())
    for warnings in ((), ("not_enough_visible",), ("low_match",)):
        for signals in ({}, {"position_jitter_mm": 25.0}, {"position_jitter_mm": 50.0, "unseen_joint_share": 0.3}):
            quality_block = block({"position_jitter_mm": "nose", "unseen_joint_share": "nose"}, warnings=warnings, **signals)
            carried = {"warnings": [{"code": c, "text": "x"} for c in warnings], "match": {"quality": "ok", "limits": {}}} \
                if warnings else {}
            output.validate_analysis({**doc, **carried, "quality": quality_block})


def test_the_block_is_a_copy_of_the_readings_and_does_not_share_them():
    readings = quality.Readings(dict(CLEAN))
    got = quality.assess(readings, (), LIMITS)
    got["signals"]["position_jitter_mm"] = 99.0
    assert readings.signals["position_jitter_mm"] == 12.0


# ---------------------------------------------------------------------------------------------- the thresholds file
def test_the_thresholds_file_holds_the_six_signals_with_increasing_limits_and_one_degraded_only():
    limits = quality.load_thresholds()
    assert tuple(limits) == output.QUALITY_SIGNALS
    assert all(0 < low < high for name, (low, high) in limits.items() if name != "heading_offset_deg")
    assert limits["position_jitter_mm"] == (21.0, 42.0) and limits["heading_offset_deg"] == (5.0, None)   # TICKET-086


@pytest.mark.parametrize("value", [5.0, 15.0, 45.0, 180.0])
def test_a_degraded_only_signal_never_makes_a_take_major_however_far_past_its_limit(value):
    """TICKET-086: Part 7 chose degraded only for the heading offset (the camera's angle, not the follower's form), so no
    reading of it alone brings the cap of 59; another signal past its major limit still makes the take major."""
    got = block(heading_offset_deg=value)
    assert got["level"] == "degraded" and got["score_cap"] is None
    assert got["reasons"] == [{"code": "heading_offset", "words": f"The body was turned about {value:.0f} degrees from the "
                               "way the example faces.", "value": value, "threshold": 5.0}]
    both = block({"position_jitter_mm": "nose"}, heading_offset_deg=value, position_jitter_mm=50.0)
    assert both["level"] == "major" and [r["code"] for r in both["reasons"]] == ["position_jitter", "heading_offset"]


def test_the_loader_reads_a_null_major_as_degraded_only_for_any_signal(tmp_path):
    path = write_thresholds(tmp_path, lambda d: d["signals"]["position_jitter_mm"].update(major=None))
    limits = quality.load_thresholds(path)
    assert limits["position_jitter_mm"] == (21.0, None) and limits["heading_offset_deg"] == (5.0, None)
    got = quality.assess(quality.Readings({**CLEAN, "position_jitter_mm": 99.0}), (), limits)
    assert got["level"] == "degraded" and got["reasons"][0]["threshold"] == 21.0


def test_the_thresholds_are_their_own_file_and_rules_json_does_not_hold_them():
    """So rules_sha256, the detection hash and the score params_sha256 cannot move (AC-Q07)."""
    assert quality.THRESHOLDS_PATH.name == "quality.json" and quality.THRESHOLDS_PATH != detect.RULES_PATH
    rules = detect.RULES_PATH.read_text()
    assert "quality" not in rules and "position_jitter_mm" not in rules


def test_the_thresholds_file_explains_which_limit_was_fitted_and_which_was_anchored():
    doc = json.loads(quality.THRESHOLDS_PATH.read_text())
    assert doc["basis"]["position_jitter_mm"].startswith("Fitted on seed 5")
    for name in ("unseen_joint_share", "missing_joint_share", "missing_frame_share", "hidden_measure_share"):
        assert doc["basis"][name].startswith("Not fitted")


def write_thresholds(tmp_path, mutate):
    doc = json.loads(quality.THRESHOLDS_PATH.read_text())
    mutate(doc)
    path = tmp_path / "quality.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.mark.parametrize("name,mutate,message", [
    ("wrong format", lambda d: d.update(format="x"), "format must be"),
    ("a signal missing", lambda d: d["signals"].pop("position_jitter_mm"), "signals must list exactly"),
    ("an extra signal", lambda d: d["signals"].update(light={"degraded": 1, "major": 2}), "signals must list exactly"),
    ("degraded not under major", lambda d: d["signals"]["position_jitter_mm"].update(degraded=50), "0 < degraded < major"),
    ("a limit that is zero", lambda d: d["signals"]["missing_joint_share"].update(degraded=0), "0 < degraded < major"),
    ("a limit that is text", lambda d: d["signals"]["missing_joint_share"].update(major="1"), "0 < degraded < major"),
    ("a limit that is a boolean", lambda d: d["signals"]["missing_joint_share"].update(major=True), "0 < degraded < major"),
    ("a pair that is not an object", lambda d: d["signals"].update(missing_joint_share=[0.1, 0.2]), "0 < degraded < major"),
    # TICKET-086: a null major is written, never left out, and a degraded-only signal still needs its degraded limit
    ("a major left out", lambda d: d["signals"]["heading_offset_deg"].pop("major"), "or major null"),
    ("a null major with no degraded", lambda d: d["signals"]["heading_offset_deg"].update(degraded=None), "or major null"),
    ("a null major with a zero degraded", lambda d: d["signals"]["heading_offset_deg"].update(degraded=0), "or major null")])
def test_a_thresholds_file_that_breaks_its_format_is_refused_naming_the_file(tmp_path, name, mutate, message):
    path = write_thresholds(tmp_path, mutate)
    with pytest.raises(quality.QualityError, match=message) as e:
        quality.load_thresholds(path)
    assert str(path) in str(e.value)


def test_a_thresholds_file_that_is_missing_or_not_json_is_refused(tmp_path):
    with pytest.raises(quality.QualityError, match="cannot read JSON"):
        quality.load_thresholds(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    with pytest.raises(quality.QualityError, match="cannot read JSON"):
        quality.load_thresholds(bad)


def test_of_clip_is_read_signals_then_assess(pose):
    clip = still(pose, 40, conf=conf_with(40, face=0.3, left_wrist=0.3, right_wrist=0.3))   # 7 of 17 joints lost
    assert quality.of_clip(clip) == quality.assess(quality.read_signals(clip))
    assert quality.of_clip(clip)["level"] == "major" and quality.of_clip(clip)["reasons"][0]["joint"] in (*FACE, "left_wrist", "right_wrist")
    assert quality.of_clip(clip, ["not_enough_visible"])["reasons"][0]["code"] == "not_enough_visible"
