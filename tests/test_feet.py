"""Foot points from Part 2's pose3d.json as an optional side input: the file, the time mapping and what is hidden
(docs/specs/foot-keypoints.md AC-FOOT-09 to AC-FOOT-11, ADR-0015, TICKET-040). Faults, words, output, the command line
and labels are in test_feet_faults.py, which uses the helpers here.

`tests/fixtures/feet/` holds two tiny hand-made files whose measures are worked out by hand (its README). The
pipeline tests build side files in Part 2's shape from a clip's own hips, knees and ankles plus a planted synthetic
foot (heel, big toe, small toe), with a controllable toe-out and roll per frame, so a fault is known by construction.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import contract, feet
from part5.detect import load_rules
from part5.feet import FOOT_MIN_CONF, FOOT_POINTS, MIN_MATCH_S, MIN_SEEN_SHARE, load_side
from part5.io import JOINTS, InputError, load_clip
from part5.measures import ALL_SPECS, FOOT_MEASURES, MEASURES, compute_feet
from part5.pipeline import REP_MODE_REASON, UNALIGNED_REASON, run
from part5.score_report import score_block

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/fixtures/feet"
WITH_FEET = FIXTURES / "side-with-feet.json"
NO_FEET = FIXTURES / "side-no-feet.json"
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
TAKE = ROOT / "fixtures/input/followers/exercise/exercise_45_good_00_correct/skeleton.json"
LATERAL = ROOT / "fixtures/input/real/lateral-raise"
TRAINER, FAST = LATERAL / "pexels-5319084/animation.json", LATERAL / "pexels-40297504/animation.json"
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
LABELS_SCHEMA = json.loads((ROOT / "contracts/labels.schema.json").read_text())
J = {name: i for i, name in enumerate(JOINTS)}
NAN = float("nan")
FOUR = list(FOOT_MEASURES)
FRAME_S = [0.0, 0.033333, 0.066667, 0.1]    # the hand-made files' four frames


def series(side):
    return {k: np.round(v, 4).tolist() for k, v in side.series.items()}


def same(a, b):
    """Two `series` dicts equal, a NaN equal to a NaN."""
    return a.keys() == b.keys() and all(np.allclose(a[k], b[k], equal_nan=True) for k in a)


def load(path=WITH_FEET, person=0, clip_t=FRAME_S, label="follower"):
    return load_side(label, path, person, clip_t)


def doc_of(path=WITH_FEET):
    return json.loads(Path(path).read_text())


def write(tmp_path, doc, name="side.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


# ---------------------------------------------------------------------------------------------------------------
# Synthetic feet for a real clip: planted flat, with a toe-out (yaw) and a roll per frame (ASM-013).
# Offsets from the ankle in the foot's frame (forward, outer edge, up), metres.
# ---------------------------------------------------------------------------------------------------------------
TEMPLATE = {"heel": (-0.07, 0.0, -0.08), "big_toe": (0.17, -0.035, -0.08), "small_toe": (0.12, 0.035, -0.08)}


def planted_feet(positions, yaw, roll):
    """The six foot points for `positions` (F, 17, 3). `yaw` and `roll` are {side: (F,) degrees}: the toe-out from
    the pelvis's forward (positive = away from the midline) and the roll about the long axis (positive = the outer
    edge goes down, the sole turning toward the midline)."""
    hip = positions[:, J["left_hip"]] - positions[:, J["right_hip"]]
    h = np.stack([hip[:, 0], hip[:, 2]], axis=1)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    f = np.stack([-h[:, 1], h[:, 0]], axis=1)    # the pelvis's forward, the hip line turned a quarter turn
    up = np.array([0.0, 1.0, 0.0])
    out = {}
    for side, sign in (("left", 1.0), ("right", -1.0)):
        th, ph = np.radians(yaw[side])[:, None], np.radians(roll[side])[:, None]
        d_xz = h * (sign * np.sin(th)) + f * np.cos(th)
        o_xz = h * (sign * np.cos(th)) + f * (-np.sin(th))
        d = np.stack([d_xz[:, 0], np.zeros(len(d_xz)), d_xz[:, 1]], axis=1)
        o = np.stack([o_xz[:, 0], np.zeros(len(o_xz)), o_xz[:, 1]], axis=1)
        o_roll, u_roll = o * np.cos(ph) - up * np.sin(ph), up * np.cos(ph) + o * np.sin(ph)
        ankle = positions[:, J[f"{side}_ankle"]]
        for part, (fwd, outer, high) in TEMPLATE.items():
            out[f"{side}_{part}"] = ankle + fwd * d + outer * o_roll + high * u_roll
    return out


def point(p, conf=1.0):
    return {"x": round(float(p[0]), 5), "y": round(float(p[1]), 5), "z": round(float(p[2]), 5), "conf": conf}


def side_doc(clip_path, yaw=7.0, roll=0.0, window=(0.2, 0.8), extra_yaw=None, extra_roll=None, feet_present=True,
             person=0, mirrored=False, hide=None):
    """A Part 2 pose3d.json for the clip at `clip_path`: its hips, knees and ankles and the planted feet.

    `yaw` and `roll` are the base angles of both feet; `extra_yaw` and `extra_roll` are `{side: degrees}` added over
    `window` (shares of the clip). `hide` is `{point name: (first share, last share)}`: that point's `conf` is 0.2 there.
    """
    clip = load_clip(clip_path)
    n = clip.n_frames
    lo, hi = int(window[0] * n), int(window[1] * n)
    angles = {}
    for kind, base, extra in (("yaw", yaw, extra_yaw or {}), ("roll", roll, extra_roll or {})):
        angles[kind] = {}
        for side in ("left", "right"):
            a = np.full(n, float(base))
            a[lo:hi] += extra.get(side, 0.0)
            angles[kind][side] = a
    points = planted_feet(clip.positions, angles["yaw"], angles["roll"])
    frames = []
    for i in range(n):
        joints = {name: point(clip.positions[i, J[name]]) for name in
                  ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")}
        person_doc = {"id": person, "joints": joints}
        if feet_present:
            person_doc["extra_joints"] = {
                name: point(points[name][i], 0.2 if hide and name in hide and
                            hide[name][0] * n <= i < hide[name][1] * n else 1.0) for name in FOOT_POINTS}
        frames.append({"frame": i, "t_ms": round(float(clip.t[i]) * 1000.0, 3), "people": [person_doc]})
    doc = {"frames": frames, "t0_pts_ms": 0.0, "provenance": {"source": "synthetic"}}
    if mirrored:
        doc["mirrored"] = True
    return doc


def analyse_with(tmp_path, expected=None, follower=None, exp_clip=EXPECTED, fol_clip=TAKE, **kw):
    """Run the pipeline with side docs (None for no file); returns the `PipelineResult`."""
    paths = {}
    for key, doc in (("expected_feet", expected), ("follower_feet", follower)):
        paths[key] = None if doc is None else str(write(tmp_path, doc, f"{key}.json"))
    return run(str(exp_clip), str(fol_clip), **paths, **kw)


def foot_faults(analysis):
    return [f for f in analysis["faults"] if f["body_part"] == "feet"]


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-09: a Part 2 file gives the four series inside its own frame
# ---------------------------------------------------------------------------------------------------------------
def test_ac_foot_09_the_hand_made_file_gives_the_hand_computed_series():
    side = load()
    s = series(side)
    assert np.allclose(s["left_foot_rotation"], [0.0, 20.0, NAN, 0.577], atol=1e-3, equal_nan=True)
    assert np.allclose(s["left_ankle_inversion"], [0.0, 0.0, NAN, 20.0], atol=0.05, equal_nan=True)
    assert np.allclose(s["right_foot_rotation"], 0.0, atol=1e-6) and np.allclose(s["right_ankle_inversion"], 0.0, atol=1e-6)
    assert side.frames_matched == 4 and side.has_points and side.source == str(WITH_FEET)


def test_ac_foot_09_a_measure_is_usable_when_a_number_in_80_percent_of_the_clip_frames():
    side = load()   # the left heel is hidden in 1 of 4 frames: 75%, under MIN_SEEN_SHARE
    assert MIN_SEEN_SHARE == 0.8
    assert side.usable == ["right_foot_rotation", "right_ankle_inversion"]
    assert side.why_not() is None


def test_ac_foot_09_the_person_is_matched_to_the_id():
    side = load(person=7)
    assert np.allclose(side.series["left_foot_rotation"], 30.0, atol=1e-3)
    assert np.allclose(side.series["left_ankle_inversion"], 0.0, atol=1e-6) and side.usable == FOUR
    assert load(person=0).series["left_foot_rotation"][1] == pytest.approx(20.0, abs=1e-3)


def test_ac_foot_09_a_mirrored_file_swaps_the_left_and_right_series(tmp_path):
    doc = doc_of()
    doc["mirrored"] = True
    side = load(write(tmp_path, doc))
    plain = load()
    assert np.allclose(side.series["right_foot_rotation"], plain.series["left_foot_rotation"], equal_nan=True)
    assert np.allclose(side.series["left_foot_rotation"], plain.series["right_foot_rotation"], equal_nan=True)
    assert np.allclose(side.series["right_ankle_inversion"], plain.series["left_ankle_inversion"], equal_nan=True)
    assert side.series["right_foot_rotation"][1] == pytest.approx(20.0, abs=1e-3)


@pytest.mark.parametrize("change,seen", [
    ({"conf": 0.49}, False),                  # just under FOOT_MIN_CONF
    ({"conf": FOOT_MIN_CONF}, True),          # at it
    ({"conf": 0.3}, False),                   # Part 2's outside-the-image mark
    ({"conf": None}, False),
    ({"x": None}, False),
    ({"y": float("nan")}, False),
    ({"z": float("inf")}, False),
    ({"conf": 1.0}, True),
])
def test_ac_foot_09_a_point_is_seen_when_present_finite_and_conf_at_least_half(tmp_path, change, seen):
    doc = doc_of()
    for fr in doc["frames"]:   # a clean left heel in every frame, then one change to the big toe of frame 0
        fr["people"][0]["extra_joints"]["left_heel"]["conf"] = 1.0
    doc["frames"][2]["people"][0]["extra_joints"]["left_big_toe"] = {"x": 0.07, "y": -0.98, "z": 0.15, "conf": 1.0}
    doc["frames"][0]["people"][0]["extra_joints"]["left_big_toe"].update(change)
    side = load(write(tmp_path, doc))
    assert bool(np.isfinite(side.series["left_foot_rotation"][0])) is seen


@pytest.mark.parametrize("hide", ["missing", "null"])
def test_ac_foot_09_a_missing_or_null_point_hides_every_measure_that_reads_it(tmp_path, hide):
    doc = doc_of()
    extra = doc["frames"][0]["people"][0]["extra_joints"]
    extra.pop("right_small_toe") if hide == "missing" else extra.update(right_small_toe=None)
    side = load(write(tmp_path, doc))
    # right_small_toe is read by right_ankle_inversion only, not by foot_rotation
    assert np.isnan(side.series["right_ankle_inversion"][0]) and np.isfinite(side.series["right_foot_rotation"][0])
    assert np.isfinite(side.series["left_ankle_inversion"][0])


def test_ac_foot_09_a_body_joint_the_measure_reads_must_be_seen_too(tmp_path):
    doc = doc_of()
    doc["frames"][0]["people"][0]["joints"]["right_hip"]["conf"] = 0.4
    side = load(write(tmp_path, doc))   # both hips are read by foot_rotation, only the foot points by ankle_inversion
    assert np.isnan(side.series["left_foot_rotation"][0]) and np.isnan(side.series["right_foot_rotation"][0])
    assert np.isfinite(side.series["left_ankle_inversion"][0])


def test_ac_foot_09_the_knee_and_ankle_are_not_read_so_a_bad_one_is_no_error_and_changes_nothing(tmp_path):
    """No foot measure reads the knee or the ankle (ADR-0015 Amendment 1): a file whose `joints` hold only the hips
    loads, and a knee or ankle that is text, missing, null or low in `conf` neither raises nor hides a measure."""
    doc = doc_of()
    want = series(load(write(tmp_path, doc, "plain.json")))
    for fr in doc["frames"]:
        joints = fr["people"][0]["joints"]
        joints["left_knee"] = {"x": "0.1", "y": 0, "z": 0, "conf": "high"}
        joints["right_knee"] = [1, 2, 3]
        joints["left_ankle"] = None
        joints["right_ankle"] = {"x": 0.0, "y": -0.9, "z": 0.0, "conf": 0.1}
    assert same(series(load(write(tmp_path, doc, "bad-knees.json"))), want)
    for fr in doc["frames"]:
        fr["people"][0]["joints"] = {k: v for k, v in fr["people"][0]["joints"].items() if k.endswith("_hip")}
    assert same(series(load(write(tmp_path, doc, "hips-only.json"))), want)


def test_ac_foot_09_unknown_names_are_ignored_and_the_time_origin_is_t0_pts(tmp_path):
    doc = doc_of()
    doc["t0_pts_ms"] = 1000.0
    for fr in doc["frames"]:
        fr["t_ms"] += 1000.0
        fr["people"][0]["extra_joints"]["left_wrist_marker"] = {"x": 0, "y": 0, "z": 0, "conf": 1.0}
        fr["people"][0]["joints"]["not_a_joint"] = {"x": 0, "y": 0, "z": 0, "conf": 1.0}
    shifted = load(write(tmp_path, doc))
    assert np.allclose(shifted.series["left_foot_rotation"], load().series["left_foot_rotation"], equal_nan=True)


def test_ac_foot_09_a_file_without_extra_joints_loads_and_has_no_usable_measure():
    side = load(NO_FEET)
    assert not side.has_points and side.usable == [] and side.frames_matched == 4
    assert all(np.isnan(v).all() for v in side.series.values())
    assert side.why_not() == "the follower feet file has no extra_joints (no foot points)"


def test_ac_foot_09_a_file_with_every_point_hidden_has_foot_points_but_no_usable_measure(tmp_path):
    doc = doc_of()
    for fr in doc["frames"]:
        for p in fr["people"][0]["extra_joints"].values():
            p["conf"] = 0.1
    side = load(write(tmp_path, doc))
    assert side.has_points and side.usable == []
    assert side.why_not() == "no foot measure is seen in 80% of the follower frames"


def test_ac_foot_09_no_file_is_an_empty_side():
    side = load_side("expected", None, 0, FRAME_S)
    assert side.source is None and side.series == {} and side.usable == []
    assert side.why_not() == "no expected feet file was given"


BAD_FILES = [
    ("not an object", [1, 2], "not a Part 2 pose3d.json"),
    ("no frames", {"frames": []}, "frames must be a non-empty list"),
    ("frames not a list", {"frames": {}}, "frames must be a non-empty list"),
    ("frame not an object", {"frames": [3]}, "frames[0] must be an object"),
    ("t_ms text", {"frames": [{"t_ms": "0", "people": []}]}, "frames[0].t_ms must be a number"),
    ("no t_ms", {"frames": [{"people": []}]}, "frames[0].t_ms must be a number"),
    ("people not a list", {"frames": [{"t_ms": 0, "people": {}}]}, "frames[0].people must be a list"),
    ("a person that is not an object", {"frames": [{"t_ms": 0, "people": [{"id": 0, "joints": {}}, 3]}]},
     "frames[0].people[1] must be an object, got int"),
    ("a person that is null", {"frames": [{"t_ms": 0, "people": [None]}]},
     "frames[0].people[0] must be an object, got NoneType"),
    ("flat joints, no people", {"frames": [{"frame": 0, "t_ms": 0.0, "joints": {}}]}, "frames[0].people must be a list"),
    ("t0 text", {"frames": [{"t_ms": 0, "people": []}], "t0_pts_ms": "0"}, "t0_pts_ms must be a number"),
    ("mirrored text", {"frames": [{"t_ms": 0, "people": []}], "mirrored": "yes"}, "mirrored must be true or false"),
]


@pytest.mark.parametrize("name,doc,message", BAD_FILES, ids=[b[0] for b in BAD_FILES])
def test_ac_foot_09_a_file_that_is_not_this_shape_is_an_input_error_naming_the_file(tmp_path, name, doc, message):
    path = write(tmp_path, doc, "feet.json")
    with pytest.raises(InputError) as e:
        load(path)
    assert str(e.value).startswith(f"{path}: ") and message in str(e.value)


@pytest.mark.parametrize("edit,message", [
    (lambda p: p.update(joints=[]), "joints must be an object"),
    (lambda p: p.update(extra_joints=[]), "extra_joints must be an object"),
    (lambda p: p["extra_joints"].update(left_heel=[0, 0, 0]), "extra_joints.left_heel must be an object"),
    (lambda p: p["extra_joints"]["left_heel"].update(x="0.1"), "extra_joints.left_heel.x must be a number or null"),
    (lambda p: p["extra_joints"]["left_heel"].update(conf="high"), "extra_joints.left_heel.conf must be a number or null"),
    (lambda p: p["joints"].update(left_hip={"x": True, "y": 0, "z": 0, "conf": 1}), "joints.left_hip.x must be a number or null"),
])
def test_ac_foot_09_a_malformed_person_or_point_names_the_frame_and_field(tmp_path, edit, message):
    doc = doc_of()
    edit(doc["frames"][1]["people"][0])
    path = write(tmp_path, doc)
    with pytest.raises(InputError) as e:
        load(path)
    assert str(e.value).startswith(f"{path}: frames[1].people[id 0]") and message in str(e.value)


def test_ac_foot_09_an_unreadable_file_or_text_that_is_not_json_is_an_input_error(tmp_path):
    with pytest.raises(InputError, match="cannot read JSON"):
        load(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(InputError, match="cannot read JSON"):
        load(bad)
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(InputError, match="cannot read JSON"):
        load(binary)


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-10: a clip frame takes the nearest side frame within half the median step of all frames (at least 0.008 s)
# ---------------------------------------------------------------------------------------------------------------
def test_ac_foot_10_a_clip_frame_within_the_window_takes_the_nearest_side_frame():
    near = load(clip_t=[t + 0.015 for t in FRAME_S])    # under half the 0.0333 step
    assert near.frames_matched == 4
    assert near.series["left_foot_rotation"][1] == pytest.approx(20.0, abs=1e-3)


def test_ac_foot_10_the_window_of_a_30_fps_side_file_is_half_its_step():
    # the side frames are 0.0333 s apart: half a step is 0.0167 s, above the floor, so a clip frame 0.0165 s after
    # the last side frame matches and one 0.0175 s after it does not
    assert load(clip_t=[0.1 + 0.0165]).frames_matched == 1
    with pytest.raises(InputError, match="no frame of the follower clip matches"):
        load(clip_t=[0.1 + 0.0175])


def test_ac_foot_10_the_window_is_at_least_half_a_60_fps_frame_for_a_very_fast_side_file(tmp_path):
    assert MIN_MATCH_S == 0.008
    doc = doc_of()
    doc["frames"] = [dict(fr, t_ms=i * 4.0) for i, fr in enumerate(doc["frames"])]   # 250 fps: half a step is 0.002 s
    path = write(tmp_path, doc)
    assert load(path, clip_t=[0.012 + 0.0075]).frames_matched == 1     # inside the 0.008 s floor
    with pytest.raises(InputError, match="no frame of the follower clip matches"):
        load(path, clip_t=[0.012 + 0.0085])


def test_ac_foot_10_the_window_is_half_the_median_step_of_all_frames_not_only_those_with_the_person(tmp_path):
    doc = doc_of()
    for i in (1, 2):    # person 7 is in frames 0 and 3 only: its own frames are 0.1 s apart, the file's are 0.0333 s
        doc["frames"][i]["people"] = [p for p in doc["frames"][i]["people"] if p["id"] != 7]
    path = write(tmp_path, doc)
    assert load(path, person=7, clip_t=[0.0, 0.1]).frames_matched == 2
    with pytest.raises(InputError, match="no frame of the follower clip matches"):
        load(path, person=7, clip_t=[0.05])    # 0.05 s from both of its frames; half the file's step is 0.0167 s


def test_ac_foot_10_a_slow_side_file_widens_the_window_to_half_its_step(tmp_path):
    doc = doc_of()
    doc["frames"] = [dict(fr, t_ms=i * 200.0) for i, fr in enumerate(doc["frames"])]   # 5 fps: half a step is 0.1 s
    path = write(tmp_path, doc)
    assert load(path, clip_t=[0.2 + 0.09]).frames_matched == 1     # 0.09 s from the frame at 0.2, inside 0.1
    with pytest.raises(InputError, match="no frame of the follower clip matches"):
        load(path, clip_t=[0.6 + 0.11])    # 0.11 s after the last frame (0.6), outside 0.1
    # a clip time midway between two side frames is 0.1 s from each: the nearer one (the earlier on a tie) is taken
    assert load(path, clip_t=[0.0, 0.31]).frames_matched == 2


def test_ac_foot_10_a_clip_frame_with_no_side_frame_in_the_window_is_nan():
    side = load(clip_t=[0.0, 0.5, 1.0])
    assert side.frames_matched == 1
    assert side.series["right_foot_rotation"][0] == pytest.approx(0.0, abs=1e-6)
    assert np.isnan(side.series["right_foot_rotation"][1:]).all()
    assert side.usable == []   # a number in 1 of 3 frames


def test_ac_foot_10_more_clip_frames_than_side_frames_each_take_the_nearest():
    side = load(person=7, clip_t=[i / 60 for i in range(7)])    # 60 fps clip, 30 fps side file
    assert side.frames_matched == 7
    assert np.allclose(side.series["left_foot_rotation"], 30.0, atol=1e-3)


def test_ac_foot_10_no_clip_frame_matched_in_time_is_an_input_error_naming_both_ranges():
    with pytest.raises(InputError) as e:
        load(clip_t=[5.0, 6.0])
    assert str(e.value).startswith(f"{WITH_FEET}: no frame of the follower clip matches a frame of this file in time")
    assert "file 0.000 to 0.100 s, clip 5.000 to 6.000 s" in str(e.value)


def test_ac_foot_10_a_person_in_no_frame_is_an_input_error_listing_the_ids():
    with pytest.raises(InputError) as e:
        load(person=3)
    assert str(e.value) == f"{WITH_FEET}: person 3 is in no frame (ids present: [0, 7])"


def test_ac_foot_10_a_text_id_is_named_in_the_ids_present_message(tmp_path):
    doc = doc_of()
    doc["frames"][0]["people"].append({"id": "left-dancer", "joints": {}})
    doc["frames"][1]["people"].append({"id": True, "joints": {}})
    path = write(tmp_path, doc)
    with pytest.raises(InputError) as e:
        load(path, person=3)
    assert str(e.value) == f"{path}: person 3 is in no frame (ids present: [0, 7, 'left-dancer', True])"
    with pytest.raises(InputError, match="person 1 is in no frame"):    # a boolean id is not the number 1
        load(path, person=1)


def test_ac_foot_10_a_person_present_in_some_frames_only_still_loads(tmp_path):
    doc = doc_of()
    del doc["frames"][2]["people"][1]
    side = load(write(tmp_path, doc), person=7, clip_t=FRAME_S)
    assert side.frames_matched == 3 and np.isnan(side.series["left_foot_rotation"][2])
    assert side.usable == []  # 3 of 4 frames is 75%


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-11: hidden, and the pair is compared on what both sides show; no feet file changes nothing
# ---------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def plain():
    return run(str(EXPECTED), str(TAKE), score=score_block)


def test_ac_foot_11_no_feet_file_changes_nothing_but_the_version(plain):
    again = run(str(EXPECTED), str(TAKE), score=score_block, expected_feet=None, follower_feet=None)
    assert again.analysis == plain.analysis
    assert "feet" not in plain.analysis["diagnostics"]
    assert plain.analysis["schema_version"] == "1.6.0"
    assert foot_faults(plain.analysis) == []


def test_ac_foot_11_a_golden_rebuilds_the_same_apart_from_the_version():
    """AC-FOOT-11: a pair without feet is what it was; the committed golden differs by `schema_version` at most."""
    golden = json.loads((ROOT / "fixtures/output/analysis.example.json").read_text())
    refs = [dict(golden[k], doc=json.loads((ROOT / golden[k]["path"]).read_text())) for k in ("expected", "follower")]
    rebuilt = contract.golden_run(*refs).analysis
    golden["schema_version"] = rebuilt["schema_version"] = "x"
    assert rebuilt == golden


def test_ac_foot_11_the_follower_alone_having_feet_hides_the_measures_with_the_reason(tmp_path):
    a = analyse_with(tmp_path, follower=side_doc(TAKE)).analysis
    info = a["diagnostics"]["feet"]
    assert info["compared"] == [] and info["hidden_reason"] == "no expected feet file was given"
    assert info["expected"] == {"source": None, "person": 0, "frames_matched": 0, "usable": []}
    assert info["follower"]["usable"] == FOUR and info["follower"]["frames_matched"] > 0
    assert foot_faults(a) == [] and a["schema_version"] == "1.6.0"


def test_ac_foot_11_a_file_without_extra_joints_is_not_an_error_and_says_why(tmp_path):
    a = analyse_with(tmp_path, expected=side_doc(EXPECTED, feet_present=False), follower=side_doc(TAKE)).analysis
    info = a["diagnostics"]["feet"]
    assert info["compared"] == [] and info["expected"]["usable"] == [] and info["follower"]["usable"] == FOUR
    assert info["hidden_reason"] == "the expected feet file has no extra_joints (no foot points)"
    both = analyse_with(tmp_path, expected=side_doc(EXPECTED, feet_present=False),
                        follower=side_doc(TAKE, feet_present=False)).analysis["diagnostics"]["feet"]
    assert both["hidden_reason"] == ("the expected feet file has no extra_joints (no foot points); "
                                     "the follower feet file has no extra_joints (no foot points)")


def test_ac_foot_11_both_clips_with_feet_compare_all_four_and_a_correct_take_has_no_foot_fault(tmp_path):
    a = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=side_doc(TAKE)).analysis
    info = a["diagnostics"]["feet"]
    assert info["compared"] == FOUR and info["hidden_reason"] is None
    assert info["expected"]["usable"] == info["follower"]["usable"] == FOUR
    assert foot_faults(a) == []


def test_ac_foot_11_a_measure_seen_in_under_80_percent_of_frames_is_left_out_and_the_pair_uses_the_rest(tmp_path):
    # the follower's left heel is unseen in 30% of its frames: both left measures read it, the right ones do not
    follower = side_doc(TAKE, hide={"left_heel": (0.3, 0.6)})
    info = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=follower).analysis["diagnostics"]["feet"]
    assert info["follower"]["usable"] == ["right_foot_rotation", "right_ankle_inversion"]
    assert info["compared"] == ["right_foot_rotation", "right_ankle_inversion"] and info["hidden_reason"] is None
    barely = side_doc(TAKE, hide={"left_heel": (0.3, 0.4)})   # 10%: still usable
    info = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=barely).analysis["diagnostics"]["feet"]
    assert info["compared"] == FOUR


def test_ac_foot_11_a_hidden_stretch_gives_no_fault_from_missing_data(tmp_path):
    follower = side_doc(TAKE, extra_yaw={"left": 25.0}, hide={"left_heel": (0.0, 1.0)})   # turned out but never seen
    a = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=follower).analysis
    assert a["diagnostics"]["feet"]["compared"] == ["right_foot_rotation", "right_ankle_inversion"]
    assert foot_faults(a) == []


def test_ac_foot_11_the_pair_is_compared_on_the_intersection_of_the_usable_measures(tmp_path):
    exp = side_doc(EXPECTED, hide={"right_small_toe": (0.0, 1.0)})    # right_ankle_inversion reads it
    info = analyse_with(tmp_path, expected=exp, follower=side_doc(TAKE)).analysis["diagnostics"]["feet"]
    assert info["follower"]["usable"] == FOUR and "right_ankle_inversion" not in info["expected"]["usable"]
    assert info["compared"] == ["left_foot_rotation", "right_foot_rotation", "left_ankle_inversion"]


def test_ac_foot_11_a_file_that_matches_no_frame_in_time_is_an_error_even_with_the_other_side_fine(tmp_path):
    late = side_doc(TAKE)
    for fr in late["frames"]:
        fr["t_ms"] += 60000.0
    with pytest.raises(InputError, match="no frame of the follower clip matches"):
        analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=late)


def test_ac_foot_11_a_take_compared_rep_by_rep_hides_the_foot_measures_with_the_reason(tmp_path):
    exp, fol = side_doc(TRAINER, window=(0.0, 0.0)), side_doc(FAST, window=(0.0, 0.0))
    with_feet = analyse_with(tmp_path, expected=exp, follower=fol, exp_clip=TRAINER, fol_clip=FAST)
    without = run(str(TRAINER), str(FAST))
    assert with_feet.reps is not None    # the lateral-raise pair is accepted rep by rep (ADR-0010)
    info = with_feet.analysis["diagnostics"]["feet"]
    assert info["compared"] == [] and info["hidden_reason"] == REP_MODE_REASON
    assert info["expected"]["usable"] == FOUR      # the files were fine; the mode is what hid them
    assert with_feet.analysis["faults"] == without.analysis["faults"]


def test_ac_foot_11_a_take_that_cannot_be_aligned_still_says_the_feet_were_not_compared(tmp_path):
    doc = json.loads(TAKE.read_text())
    for fr in doc["frames"]:
        fr["joints"] = {}
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps(doc))
    res = run(str(EXPECTED), str(empty), expected_feet=str(write(tmp_path, side_doc(EXPECTED), "e.json")),
              follower_feet=str(write(tmp_path, side_doc(TAKE), "f.json")))
    assert res.analysis["warnings"][0]["code"] == "no_usable_measures"
    assert res.analysis["diagnostics"]["feet"]["hidden_reason"] == UNALIGNED_REASON


def test_ac_foot_11_a_foot_measure_with_no_rules_entry_is_computed_but_never_reported(tmp_path):
    rules = load_rules()
    rules["measures"] = {k: v for k, v in rules["measures"].items() if k not in ("foot_rotation", "ankle_inversion")}
    res = analyse_with(tmp_path, expected=side_doc(EXPECTED), follower=side_doc(TAKE, extra_yaw={"left": 25.0}),
                       rules=rules)
    assert res.analysis["diagnostics"]["feet"]["compared"] == FOUR and foot_faults(res.analysis) == []


def test_ac_foot_11_the_foot_measures_are_not_in_the_body_registry():
    """AC-FOOT-08: separate registry, so alignment, the guard and the similarity term cannot move."""
    assert not set(FOOT_MEASURES) & set(MEASURES) and set(ALL_SPECS) == set(MEASURES) | set(FOOT_MEASURES)
    assert all(m.body_part == "feet" and m.joint.endswith("_ankle") and m.kind == "direction"
               for m in FOOT_MEASURES.values())
    with np.errstate(all="ignore"):
        assert set(compute_feet({n: np.zeros((1, 3)) for n in feet.BODY_POINTS + FOOT_POINTS})) == set(FOOT_MEASURES)
