"""TICKET-041: the phone's gravity as the clip's up (part3/gravity.py, geometry.body_up(gravity_up=...)).

Fixtures are synthetic. A standing person is filmed by a camera pitched 25 degrees: Part 2's canonical axes follow the
camera, so the body is turned 25 degrees about x in the input and the true vertical is that same turn of +y. Part 2
(TICKET-055) writes that vertical as `up` on every person in every frame; the fixtures write it the same way.
"""

import copy
import json

import numpy as np
import pytest

from clipkit import make_doc, skeleton_arrays
from part3 import cli, contract, jsonschema_lite, geometry as g, gravity
from part3.joints import INDEX, swap_index
from part3.views import part4 as part4_view
from test_body_up_floor_work import leaning
from test_body_up_one_legged import standing_body

PITCH_DEG = 25.0


def with_gravity(doc, up, top=True):
    """A copy of `doc` with `up` on its person in every frame (and Part 2's top-level block)."""
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        for person in frame["people"]:
            person["up"] = [float(c) for c in up]
    if top:
        out["gravity"] = {"up_camera": [0.0, -1.0, 0.0], "camera_frame": "opencv", "source": "devicemotion",
                          "t_ms": [0, 1000], "samples": 30, "tilt_deg": 0.0}
    return out


def pitched_standing(deg=PITCH_DEG, frames=40):
    turn = g.rotation([1.0, 0.0, 0.0], deg)
    J = np.stack([standing_body() @ turn.T] * frames)
    return J, turn @ np.array([0.0, 1.0, 0.0])


def run(doc, **kwargs):
    trace = {}
    out = cli.process(doc, trace=trace, **kwargs)
    return out, trace


def valid(out):
    assert jsonschema_lite.validate(out, contract.SCHEMAS["skeleton"]["schema"]) == []
    rendered = part4_view.render(out, keyframes="every:10")
    assert jsonschema_lite.validate(rendered, contract.SCHEMAS["skeleton-part4"]["schema"]) == []


def test_tilted_phone_standing_person_gets_true_vertical_within_one_degree():
    J, vertical = pitched_standing()
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical)
    out, trace = run(doc)
    assert out["frame"]["up_source"] == "gravity" and trace["up_source"] == "gravity"
    assert float(g.angle_between(trace["up_in_input"], vertical)) <= 1.0
    block = out["frame"]["gravity"]
    assert block["frames_used"] == block["frames_total"] == 40 and block["spread_deg"] == 0.0
    assert "warning" not in block and "gravity_ignored" not in out["frame"]
    valid(out)


def test_the_same_pitch_without_gravity_is_still_the_body_rule_and_close_here():
    J, vertical = pitched_standing()
    _, trace = run(make_doc(J, np.ones(J.shape[:2])))
    assert trace["up_source"] == "standing_frames"


@pytest.mark.parametrize("floor_work", [False, True])
def test_lying_push_up_with_gravity_gets_true_vertical(floor_work):
    J = leaning(85.0)   # a body lying almost flat under a level phone; true vertical is the input's +y
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), [0.0, 1.0, 0.0])
    out, trace = run(doc, floor_work=floor_work)
    assert out["frame"]["up_source"] == "gravity"
    assert float(g.angle_between(trace["up_in_input"], [0, 1, 0])) <= 1.0
    assert out["frame"]["gravity"]["body_rule_angle_deg"] > 80.0
    assert ("warning" in out["frame"]["gravity"]) is (not floor_work)
    valid(out)


def test_gravity_replaces_the_floor_work_hint_and_the_standing_rule():
    J = leaning(60.0)
    plain = run(make_doc(J, np.ones(J.shape[:2])), floor_work=True)[0]
    assert plain["frame"]["up_source"] == "input_up_floor_work"
    tilted = with_gravity(make_doc(J, np.ones(J.shape[:2])), g.rotation([1, 0, 0], 20.0) @ [0, 1, 0])
    out, trace = run(tilted, floor_work=True)
    assert out["frame"]["up_source"] == "gravity" and out["frame"]["floor_work"] is True
    assert float(g.angle_between(trace["up_in_input"], [0, 1.0 * np.cos(np.radians(20)), np.sin(np.radians(20))])) < 1e-6


def test_disagreement_with_a_confident_standing_estimate_warns_and_still_prefers_gravity():
    assert gravity.MAX_BODY_ANGLE_WARN_DEG == 25.0 and not hasattr(gravity, "DISAGREE_DEG")
    J = np.stack([standing_body()] * 40)
    vertical = g.rotation([1.0, 0.0, 0.0], 40.0) @ np.array([0.0, 1.0, 0.0])
    out, trace = run(with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical))
    assert out["frame"]["up_source"] == "gravity"
    assert float(g.angle_between(trace["up_in_input"], vertical)) < 1e-6
    assert "40.0 degrees" in out["frame"]["gravity"]["warning"]
    assert out["frame"]["gravity"]["body_rule_source"] == "standing_frames"
    valid(out)


def test_agreement_inside_the_threshold_records_no_warning():
    J = np.stack([standing_body()] * 40)
    vertical = g.rotation([1.0, 0.0, 0.0], 20.0) @ np.array([0.0, 1.0, 0.0])
    out, _ = run(with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical))
    assert "warning" not in out["frame"]["gravity"]


def test_without_gravity_the_output_is_unchanged():
    J, vertical = pitched_standing()
    plain = make_doc(J, np.ones(J.shape[:2]))
    stripped = with_gravity(plain, vertical)
    stripped["frames"] = [{**f, "people": [{k: v for k, v in p.items() if k != "up"} for p in f["people"]]}
                          for f in stripped["frames"]]
    del stripped["gravity"]
    a, b = cli.process(plain), cli.process(stripped)
    assert json.dumps(a) == json.dumps(b)
    assert set(a["frame"]) <= {"origin", "x", "y", "z", "up_source", "floor_work"}


def test_a_mirrored_take_mirrors_the_vertical_with_the_joints():
    turn = g.rotation([0.0, 0.0, 1.0], 20.0)
    J = np.stack([standing_body() @ turn.T] * 40)
    vertical = turn @ np.array([0.0, 1.0, 0.0])
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2]), extra={"mirrored": True}), vertical)
    _, trace = run(doc)
    expected = vertical * np.array([-1.0, 1.0, 1.0])
    assert float(g.angle_between(trace["up_in_input"], expected)) < 1e-6


def test_invalid_frames_take_the_nearest_valid_ones():
    J, vertical = pitched_standing()
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical)
    for i in range(0, 6):
        doc["frames"][i]["people"][0]["up"] = "wild"
    out, trace = run(doc)
    assert out["frame"]["up_source"] == "gravity" and out["frame"]["gravity"]["frames_used"] == 34
    assert float(g.angle_between(trace["up_in_input"], vertical)) < 1e-6
    assert float(feet_to_neck_errors(out).max()) <= 1.0


BAD = {
    "not unit length": [0.0, 2.0, 0.0],
    "zero": [0.0, 0.0, 0.0],
    "two numbers": [0.0, 1.0],
    "strings": ["0", "1", "0"],
    "booleans": [False, True, False],
    "not a list": "up",
    "null": None,
}


@pytest.mark.parametrize("name", list(BAD))
def test_malformed_gravity_is_ignored_with_a_recorded_reason(name):
    J, vertical = pitched_standing()
    plain = make_doc(J, np.ones(J.shape[:2]))
    doc = with_gravity(plain, [0, 1, 0])
    for frame in doc["frames"]:
        frame["people"][0]["up"] = BAD[name]
    out, trace = run(doc)
    baseline = cli.process(plain)
    assert out["frame"]["up_source"] == baseline["frame"]["up_source"] == "standing_frames"
    assert out["frame"]["gravity_ignored"].startswith("no frame holds a valid up")
    assert "gravity" not in out["frame"]
    assert {**out, "frame": baseline["frame"], "input": baseline["input"]} == baseline
    valid(out)


def test_non_finite_gravity_is_ignored():
    J, _ = pitched_standing()
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), [0, 1, 0])
    for frame in doc["frames"]:
        frame["people"][0]["up"] = [float("nan"), 1.0, 0.0]
    assert "gravity_ignored" in cli.process(doc)["frame"]


def test_gravity_block_without_per_frame_values_is_ignored():
    J, _ = pitched_standing()
    doc = make_doc(J, np.ones(J.shape[:2]))
    doc["gravity"] = {"up_camera": [0, -1, 0]}
    out = cli.process(doc)
    assert out["frame"]["up_source"] == "standing_frames" and "gravity_ignored" in out["frame"]


def test_most_frames_invalid_is_ignored_and_a_minority_is_dropped():
    J, vertical = pitched_standing()
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical)
    for i in range(30):
        doc["frames"][i]["people"][0]["up"] = [0.0, 3.0, 0.0]
    assert cli.process(doc)["frame"]["gravity_ignored"] == "only 10 of 40 frames hold a valid up"
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical)
    for i in range(10):
        del doc["frames"][i]["people"][0]["up"]
    out = cli.process(doc)
    assert out["frame"]["up_source"] == "gravity"
    assert (out["frame"]["gravity"]["frames_used"], out["frame"]["gravity"]["frames_total"]) == (30, 40)


def test_opposite_halves_refuse_and_a_modest_spread_warns():
    J, vertical = pitched_standing()
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical)
    for i in range(20):
        doc["frames"][i]["people"][0]["up"] = [float(c) for c in -vertical]
    assert "gravity_ignored" in cli.process(doc)["frame"]   # two opposite halves: no frame is near the median
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical)
    for i in range(20):
        doc["frames"][i]["people"][0]["up"] = [float(c) for c in g.rotation([1, 0, 0], 8.0) @ vertical]
    block = cli.process(doc)["frame"]["gravity"]
    assert 3.9 < block["spread_deg"] < 4.1 and "warning" not in block
    for i in range(20):
        doc["frames"][i]["people"][0]["up"] = [float(c) for c in g.rotation([1, 0, 0], 20.0) @ vertical]
    block = cli.process(doc)["frame"]["gravity"]
    assert block["spread_deg"] > 5.0 and "per-frame ups tilt" in block["warning"]


def test_all_people_each_use_their_own_gravity():
    J, vertical = pitched_standing(frames=20)
    doc = with_gravity(make_doc(J, np.ones(J.shape[:2])), vertical)
    results = cli.process_all(doc)
    assert [s["frame"]["up_source"] for _, s in results] == ["gravity"]


def test_the_schema_enum_names_gravity():
    for name in ("skeleton", "skeleton-part4"):
        enum = contract.SCHEMAS[name]["schema"]["properties"]["frame"]["properties"]["up_source"]["enum"]
        assert "gravity" in enum


# --- Part 2's per-frame canonical axes (B1, B2) ---------------------------------------------------------
CAM_UP = np.array([0.0, -1.0, 0.0])
TILT_CAMERA_DEG = 35.0   # TICKET-041 AC-2


def frame_axes(kp):
    """Part 2 canonical.frame_axes: y = camera up, x = hip line without its up part, z = x cross y."""
    t = (kp[INDEX["left_hip"]] + kp[INDEX["right_hip"]]) / 2
    x = kp[INDEX["left_hip"]] - kp[INDEX["right_hip"]]
    x = x - x.dot(CAM_UP) * CAM_UP
    x /= np.linalg.norm(x)
    return np.stack([x, CAM_UP, np.cross(x, CAM_UP)], axis=1), t


def part2_take(yaws_deg, pitch=TILT_CAMERA_DEG, roll=0.0, mirrored=False):
    """A pose3d document as Part 2 writes it: a standing body yawing by `yaws_deg` filmed by a tilted camera,
    joints in each frame's own canonical axes, and per-frame up = R^T up_camera."""
    body = standing_body()
    tilt = g.rotation([1, 0, 0], pitch) @ g.rotation([0, 0, 1], roll)
    up_cam = tilt @ np.diag([1.0, -1.0, -1.0]) @ np.array([0.0, 1.0, 0.0])
    flip = np.array([-1.0, 1.0, 1.0])
    frames, ups = [], []
    for yaw in yaws_deg:
        cam = (tilt @ np.diag([1.0, -1.0, -1.0]) @ (g.rotation([0, 1, 0], yaw) @ body.T)).T + [0, 0, 3.0]
        if mirrored:
            cam = (cam * flip)[swap_index()]
        R, t = frame_axes(cam)
        frames.append((cam - t) @ R)
        ups.append(R.T @ (up_cam * flip if mirrored else up_cam))
    J = np.stack(frames)
    doc = make_doc(J, np.ones(J.shape[:2]), extra={"mirrored": True} if mirrored else None)
    for frame, u in zip(doc["frames"], ups):
        frame["people"][0]["up"] = [round(float(c), 6) for c in u]
    doc["gravity"] = {"up_camera": [round(float(c), 6) for c in up_cam]}
    return doc


def feet_to_neck_errors(out):
    J, _, present = skeleton_arrays(out)
    neck = 0.5 * (J[:, INDEX["left_shoulder"]] + J[:, INDEX["right_shoulder"]])
    ankle = 0.5 * (J[:, INDEX["left_ankle"]] + J[:, INDEX["right_ankle"]])
    return g.angle_between((neck - ankle)[present], [0.0, 1.0, 0.0])


YAWS = {
    "no turn": [0.0] * 40,
    "hip jitter 15": list(15 * np.sin(np.linspace(0, 6 * np.pi, 40))),
    "quarter turn": list(np.linspace(0, 90, 40)),
    "full turn": list(np.linspace(0, 360, 40, endpoint=False)),
}


@pytest.mark.parametrize("name", list(YAWS))
@pytest.mark.parametrize("roll", [0.0, 10.0])
def test_every_frame_is_vertical_whatever_the_tilt_and_the_yaw(name, roll):
    out, trace = run(part2_take(YAWS[name], roll=roll))
    assert out["frame"]["up_source"] == "gravity" and "warning" not in out["frame"]["gravity"]
    assert out["frame"]["gravity"]["spread_deg"] < 0.01
    assert float(feet_to_neck_errors(out).max()) <= 3.0
    valid(out)


def test_the_single_median_vector_fails_on_a_quarter_turn_but_per_frame_does_not():
    doc = part2_take(YAWS["quarter turn"])
    J, _ = (np.array([[[p["joints"][n][k] for k in "xyz"] for n in p["joints"]] for p in
                      (f["people"][0] for f in doc["frames"])]), None)
    ups = np.array([f["people"][0]["up"] for f in doc["frames"]])
    single = g.normalize(np.median(ups, axis=0))
    names = list(doc["frames"][0]["people"][0]["joints"])

    def worst(up):
        F, _ = g.pelvis_frame(J, up)
        neck = 0.5 * (F[:, names.index("left_shoulder")] + F[:, names.index("right_shoulder")])
        ankle = 0.5 * (F[:, names.index("left_ankle")] + F[:, names.index("right_ankle")])
        return float(g.angle_between(neck - ankle, [0, 1, 0]).max())

    assert worst(single) > 10.0 and worst(ups) < 0.01


@pytest.mark.parametrize("name", ["no turn", "quarter turn"])
def test_a_mirrored_part2_take_is_vertical_in_every_frame(name):
    out, _ = run(part2_take(YAWS[name], roll=10.0, mirrored=True))
    assert out["frame"]["up_source"] == "gravity"
    assert float(feet_to_neck_errors(out).max()) <= 3.0


def test_the_record_counts_the_frames_that_survive_the_hip_check():
    doc = part2_take(YAWS["no turn"])
    for i in (0, 1):   # hips on top of each other: dropped before gravity is read
        for joint in ("left_hip", "right_hip"):
            doc["frames"][i]["people"][0]["joints"][joint].update(x=0.0, y=0.9, z=0.0)
    block = cli.process(doc)["frame"]["gravity"]
    assert block["frames_used"] == block["frames_total"] == 38


def test_one_sign_flipped_frame_is_dropped_not_fatal():
    doc = part2_take(YAWS["quarter turn"])
    doc["frames"][7]["people"][0]["up"] = [-c for c in doc["frames"][7]["people"][0]["up"]]
    out, _ = run(doc)
    assert out["frame"]["up_source"] == "gravity" and out["frame"]["gravity"]["frames_used"] == 39
    assert float(feet_to_neck_errors(out).max()) <= 3.0


def test_survivors_that_refuse_do_not_keep_the_first_record():
    body = standing_body()
    turned = body @ g.rotation([0, 1, 0], 90.0).T   # hips along z
    J = np.stack([turned] * 19 + [body] * 21)
    doc = make_doc(J, np.ones(J.shape[:2]))
    for i, frame in enumerate(doc["frames"]):
        frame["people"][0]["up"] = "bad" if i < 19 else [1.0, 0.0, 0.0]   # up along x: no hip line left in the last 21
    out = cli.process(doc)   # 21 of 40 valid at first; the 21 frames framed by it are invalid, the survivors have none
    assert "gravity" not in out["frame"] and out["frame"]["up_source"] != "gravity"
    assert out["frame"]["gravity_ignored"].startswith("no frame holds a valid up")


def moving_phone_take(pitches, assumed_pitch):
    """Part 2's input for a phone that pitched through `pitches` while one up_camera (at `assumed_pitch`) was written."""
    body = standing_body()
    world = np.diag([1.0, -1.0, -1.0])
    up_cam = g.rotation([1, 0, 0], assumed_pitch) @ world @ np.array([0.0, 1.0, 0.0])
    frames, ups = [], []
    for pitch in pitches:
        cam = (g.rotation([1, 0, 0], pitch) @ world @ body.T).T + [0, 0, 3.0]
        R, t = frame_axes(cam)
        frames.append((cam - t) @ R)
        ups.append(R.T @ up_cam)
    J = np.stack(frames)
    doc = make_doc(J, np.ones(J.shape[:2]))
    for frame, u in zip(doc["frames"], ups):
        frame["people"][0]["up"] = [round(float(c), 6) for c in u]
    return doc


def test_a_moving_phone_has_zero_spread_and_only_the_largest_body_angle_sees_it():
    block = cli.process(moving_phone_take(np.linspace(0, 60, 40), 30.0))["frame"]["gravity"]
    assert block["spread_deg"] == 0.0
    assert block["body_rule_max_deg"] > gravity.MAX_BODY_ANGLE_WARN_DEG and block["body_rule_angle_deg"] < 20.0
    assert "phone may have moved" in block["warning"]


def test_a_steady_phone_and_a_floor_work_clip_get_no_largest_angle_warning():
    steady = cli.process(moving_phone_take([30.0] * 40, 30.0))["frame"]["gravity"]
    assert steady["body_rule_max_deg"] < 0.1 and "warning" not in steady
    moving = moving_phone_take(np.linspace(0, 60, 40), 30.0)
    assert "warning" not in cli.process(moving, floor_work=True)["frame"]["gravity"]


def tilted_standing_doc(deg):
    """A still standing body with gravity `deg` degrees off its line."""
    J = np.stack([standing_body()] * 40)
    return with_gravity(make_doc(J, np.ones(J.shape[:2])), g.rotation([1, 0, 0], deg) @ np.array([0.0, 1.0, 0.0]))


@pytest.mark.parametrize("deg,warns", [(24.0, False), (25.0, False), (26.0, True)])
def test_the_largest_angle_boundary_is_25_degrees(deg, warns):
    block = cli.process(tilted_standing_doc(deg))["frame"]["gravity"]
    assert abs(block["body_rule_max_deg"] - deg) < 0.01
    assert ("warning" in block) is warns


UPPER = [name for name in INDEX if not name.endswith(("_hip", "_knee", "_ankle"))]


def hinge_clip(deg, single_leg, frames=40):
    """A still level phone on a hinge that goes out to `deg` and returns; with `single_leg` the right leg trails
    back by the same angle, knees straight (a single-leg RDL); otherwise a good morning (legs stay vertical)."""
    body = standing_body()
    hip = 0.5 * (body[INDEX["left_hip"]] + body[INDEX["right_hip"]])
    out = []
    for a in deg * np.sin(np.linspace(0.0, np.pi, frames)):
        R = g.rotation([1.0, 0.0, 0.0], a)
        frame = body.copy()
        for name in UPPER:
            frame[INDEX[name]] = hip + R @ (body[INDEX[name]] - hip)
        if single_leg:
            pivot = body[INDEX["right_hip"]]
            for name in ("right_knee", "right_ankle"):
                frame[INDEX[name]] = pivot + g.rotation([1.0, 0.0, 0.0], a) @ (body[INDEX[name]] - pivot)
        out.append(frame)
    return np.stack(out)


@pytest.mark.parametrize("deg,single_leg", [(90, False), (120, False), (60, True), (90, True)])
def test_a_hinge_under_a_still_level_phone_gets_no_phone_moved_warning(deg, single_leg):
    J = hinge_clip(deg, single_leg)
    out = cli.process(with_gravity(make_doc(J, np.ones(J.shape[:2])), [0.0, 1.0, 0.0]))
    block = out["frame"]["gravity"]
    assert out["frame"]["up_source"] == "gravity" and "warning" not in block
    assert block.get("body_rule_max_deg", 0.0) <= gravity.MAX_BODY_ANGLE_WARN_DEG


def test_a_clip_with_no_aligned_frame_records_no_largest_angle():
    J = hinge_clip(90, False)
    J = J[10:30]   # the middle of the hinge only
    block = cli.process(with_gravity(make_doc(J, np.ones(J.shape[:2])), [0.0, 1.0, 0.0]))["frame"]["gravity"]
    assert "body_rule_max_deg" not in block and "warning" not in block
