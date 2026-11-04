"""The page's pure logic, run in Node against the real payload (docs/specs/viewer.md, AC-V01 to AC-V04).

`web/joints.js` (fallback mapping, jump target, highlight window) and `Playback`, `groundFrame`, `groundClip`
and `boundsOf` in `web/viewer.js` (AC-V22) have no DOM, so Node imports them directly. The producer's own mapping is the reference
(`part5.joints_map.fault_joints`, ADR-0006: the two tables are tested against each other).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from part5 import api
from part5.detect import generic
from part5.joints_map import fault_joints
from part5.measures import MEASURES

ROOT = Path(__file__).resolve().parent.parent
JOINTS_URL = (ROOT / "web/joints.js").as_uri()
VIEWER_URL = (ROOT / "web/viewer.js").as_uri()
API_URL = (ROOT / "web/api.js").as_uri()
NODE = shutil.which("node")


def node_major():
    if not NODE:
        return 0
    return int(subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")[0])


pytestmark = pytest.mark.skipif(node_major() < 22, reason="needs Node 22 or later to import the page's modules")


def run_node(script, payload):
    """Run an ES module script that reads `payload` (JSON on stdin) and prints one JSON value."""
    prelude = ("const payload = JSON.parse(await new Promise((r) => { let s = ''; process.stdin.setEncoding('utf8');"
               " process.stdin.on('data', (c) => { s += c; }); process.stdin.on('end', () => r(s)); }));\n")
    done = subprocess.run([NODE, "--no-warnings", "--input-type=module", "-e", prelude + script],
                          input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def every_measure_and_side():
    """(measure, side, joint as the producer names it) for every measure and valid side."""
    cases = []
    for name, spec in MEASURES.items():
        measure, side = generic(name)
        cases.append({"measure": measure, "side": side, "joint": spec.joint})
        if side == "left":
            cases.append({"measure": measure, "side": "right", "joint": spec.joint.replace("left_", "right_")})
            cases.append({"measure": measure, "side": "both", "joint": spec.joint.split("_", 1)[1]})
    return cases


# ----------------------------------------------------------------------------- AC-V03: fallback mapping

def test_AC_V03_the_viewer_fallback_agrees_with_the_producer_for_every_measure_and_side():
    cases = every_measure_and_side()
    assert len(cases) > 20
    script = (f'import {{ fallbackJoints }} from "{JOINTS_URL}";\n'
              "console.log(JSON.stringify(payload.map((fault) => fallbackJoints(fault))));")
    theirs = run_node(script, cases)
    assert theirs == [fault_joints(case) for case in cases]


@pytest.mark.parametrize("fault,expected", [
    ({"joint": "elbow", "side": "both"}, ["left_elbow", "right_elbow"]),
    ({"joint": "left_elbow", "side": "both"}, ["left_elbow", "right_elbow"]),
    ({"joint": "right_knee", "side": "right"}, ["right_knee"]),
    ({"joint": "spine", "side": "center"}, ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]),
    ({"joint": "shoulders", "side": "center"}, ["left_shoulder", "right_shoulder"]),
    ({"joint": "neck", "side": "center"}, ["nose", "left_shoulder", "right_shoulder"]),
    ({"joint": "wobble", "side": "both"}, []),
])
def test_AC_V03_a_1_0_fault_without_joints_highlights_by_the_table(fault, expected):
    script = (f'import {{ faultJoints }} from "{JOINTS_URL}";\n'
              "console.log(JSON.stringify(faultJoints(payload)));")
    assert run_node(script, fault) == expected


def test_a_fault_that_carries_joints_uses_them_not_the_table():
    script = (f'import {{ faultJoints }} from "{JOINTS_URL}";\n'
              "console.log(JSON.stringify(faultJoints(payload)));")
    own = {"joint": "spine", "side": "center", "joints": ["left_hip"]}
    assert run_node(script, own) == ["left_hip"]
    assert run_node(script, {**own, "joints": ["not_a_joint"]}) == ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]


# ----------------------------------------------------------------------------- the size in words

SIZE_SCRIPT = (f'import {{ sizeSentence }} from "{JOINTS_URL}";\n'
               "console.log(JSON.stringify(payload.map((fault) => sizeSentence(fault))));")


def test_the_size_reads_without_a_sign_next_to_its_direction_word():
    faults = [{"magnitude_deg": -29.9, "direction": "less"}, {"magnitude_deg": 8.04, "direction": "more"},
              {"magnitude_deg": -0.04, "direction": "less"}]
    assert run_node(SIZE_SCRIPT, faults) == [
        "29.9 degrees less than the example", "8.0 degrees more than the example",
        "0.0 degrees less than the example"]


def test_a_real_less_fault_is_shown_without_its_minus_sign():
    shallow = next(t["id"] for t in api._samples_listing()["followers"]
                   if t["set"] == "exercise" and t["angle"] == "front" and t["light"] == "good"
                   and t["faults"] and t["faults"][0]["type"] == "knees_shallow")
    faults = analysed("exercise", shallow)["analysis"]["faults"]
    less = [f for f in faults if f["direction"] == "less"]
    assert less and all(f["magnitude_deg"] < 0 for f in less)  # the file is signed, the page is not
    for words in run_node(SIZE_SCRIPT, less):
        assert "-" not in words and words.endswith(" degrees less than the example")


@pytest.mark.parametrize("page", ["app.js", "preview.js"])
def test_the_page_builds_the_size_only_through_the_shared_sentence(page):
    source = (ROOT / "web" / page).read_text()
    assert "sizeSentence(" in source and "magnitude_deg.toFixed" not in source


# ----------------------------------------------------------------------------- AC-V01, AC-V02 on a real analysis

def analysed(expected, follower):
    status, _, raw = api.handle("POST", "/api/analyse", json.dumps(
        {"expected": {"sample": expected}, "follower": {"sample": follower}}).encode(), base_path="/")
    assert status == 200
    return json.loads(raw)


@pytest.fixture(scope="module")
def foot_out():
    follower = next(t["id"] for t in api._samples_listing()["followers"]
                    if t["set"] == "exercise" and t["faults"] and t["faults"][0]["type"] == "foot_out")
    return analysed("exercise", follower)


def reference_target(exp_to_fol, fault):
    return next((i for i, v in enumerate(exp_to_fol) if v >= fault["follower_frames"][0]), len(exp_to_fol) - 1)


def test_AC_V02_the_jump_target_and_highlight_window_follow_the_follower_frames(foot_out):
    exp_to_fol = foot_out["replay"]["exp_to_fol"]
    faults = foot_out["analysis"]["faults"]
    assert faults
    script = (f'import {{ jumpTarget, faultWindow, highlightedAt }} from "{JOINTS_URL}";\n'
              "const out = payload.faults.map((fault) => ({ target: jumpTarget(payload.map, fault),"
              " window: faultWindow(payload.map, fault),"
              " lit: payload.map.map((_, i) => highlightedAt(payload.map, fault, i)) }));\n"
              "console.log(JSON.stringify(out));")
    out = run_node(script, {"map": exp_to_fol, "faults": faults})
    for fault, got in zip(faults, out):
        target = reference_target(exp_to_fol, fault)
        assert got["target"] == target and got["window"]["start"] == target
        last = max(i for i, v in enumerate(exp_to_fol) if i == target or (i > target and v <= fault["follower_frames"][1]))
        assert got["window"]["end"] == last
        lit = [i for i, joints in enumerate(got["lit"]) if joints]
        assert lit == list(range(target, last + 1)), "the highlight lasts exactly over the window"
        assert all(joints == fault["joints"] for joints in got["lit"][target:last + 1])
        assert all(joints == [] for joints in got["lit"][:target] + got["lit"][last + 1:])


def test_a_one_frame_fault_still_jumps_and_highlights_one_frame():
    script = (f'import {{ faultWindow, highlightedAt }} from "{JOINTS_URL}";\n'
              "const fault = { follower_frames: [5, 5], joints: ['left_knee'] };\n"
              "const map = [0, 1, 2, 3, 4, 5, 6, 7];\n"
              "const skipped = [0, 1, 2, 3, 4, 7, 8, 9];\n"  # the alignment jumped over follower frame 5
              "console.log(JSON.stringify({ one: faultWindow(map, fault), skipped: faultWindow(skipped, fault),"
              " lit: map.map((_, i) => highlightedAt(map, fault, i).length) }));")
    out = run_node(script, None)
    assert out["one"] == {"start": 5, "end": 5} and out["skipped"] == {"start": 5, "end": 5}
    assert out["lit"] == [0, 0, 0, 0, 0, 1, 0, 0]


# ----------------------------------------------------------------------------- AC-V01, AC-V04: the clock

def test_AC_V01_the_follower_shown_at_expected_frame_i_is_exp_to_fol_i(foot_out):
    exp_to_fol = foot_out["replay"]["exp_to_fol"]
    script = (f'import {{ Playback }} from "{VIEWER_URL}";\n'
              "const p = new Playback({ frames: payload.length, fps: 30, expToFol: payload });\n"
              "const shown = payload.map((_, i) => { p.seek(i); return [p.frame, p.followerFrame]; });\n"
              "console.log(JSON.stringify(shown));")
    shown = run_node(script, exp_to_fol)
    assert shown == [[i, v] for i, v in enumerate(exp_to_fol)]


def test_AC_V04_play_advances_pause_holds_scrub_and_speed_work_and_the_clip_loops():
    script = (f'import {{ Playback }} from "{VIEWER_URL}";\n'
              "const seen = [];\n"
              "const p = new Playback({ frames: 90, fps: 30, expToFol: Array.from({ length: 90 }, (_, i) => i),"
              " onChange: (s) => seen.push(s.playing) });\n"
              "const log = {};\n"
              "p.tick(1); log.idle = p.frame;\n"                       # not playing: the clock does not move
              "p.play(); p.tick(1); log.played = p.frame;\n"           # 30 fps for one second
              "p.pause(); p.tick(1); log.paused = p.frame;\n"
              "p.setSpeed(2); p.play(); p.tick(0.5); log.fast = p.frame;\n"
              "p.setSpeed(0.25); p.pause(); p.seek(10); p.play(); p.tick(1); log.slow = p.frame;\n"
              "p.setSpeed(1); p.seek(85); p.tick(0.5); log.looped = p.frame;\n"
              "p.pause(); p.seek(500); log.high = p.frame; p.seek(-4); log.low = p.frame;\n"
              "p.step(1); log.step = p.frame; p.setSpeed(3); log.badSpeed = p.speed;\n"
              "log.events = seen;\n"
              "console.log(JSON.stringify(log));")
    log = run_node(script, None)
    assert log["idle"] == 0 and log["played"] == 30 and log["paused"] == 30
    assert log["fast"] == 60 and log["slow"] == 17 and log["looped"] == 10
    assert log["high"] == 89 and log["low"] == 0 and log["step"] == 1 and log["badSpeed"] == 1
    assert log["events"][0] is True and False in log["events"]  # onChange reports play and pause


def test_AC_V02_selecting_a_fault_pauses_jumps_and_lights_its_joints_only_while_the_run_lasts(foot_out):
    fault = foot_out["analysis"]["faults"][0]
    exp_to_fol = foot_out["replay"]["exp_to_fol"]
    script = (f'import {{ Playback }} from "{VIEWER_URL}";\n'
              "const p = new Playback({ frames: payload.map.length, fps: 30, expToFol: payload.map });\n"
              "p.play();\n"
              "p.selectFault(payload.fault);\n"
              "const at = { frame: p.frame, playing: p.playing, lit: p.highlighted };\n"
              "p.seek(0); const before = p.highlighted;\n"
              "p.seek(payload.map.length - 1); const after = p.highlighted;\n"
              "p.selectFault(null); p.seek(at.frame); const cleared = p.highlighted;\n"
              "console.log(JSON.stringify({ at, before, after, cleared }));")
    out = run_node(script, {"map": exp_to_fol, "fault": fault})
    assert out["at"] == {"frame": reference_target(exp_to_fol, fault), "playing": False, "lit": fault["joints"]}
    assert out["before"] == [] and out["after"] == [] and out["cleared"] == []


# ----------------------------------------------------------------------------- AC-V21: the Mode select (AC-PROF-15)

def mode_page(call, payload):
    """Evaluate `call` over `payload` with joints.js as `j` and api.js as `a`, the modules the page imports."""
    script = (f'import * as j from "{JOINTS_URL}";\nimport * as a from "{API_URL}";\n'
              f"console.log(JSON.stringify({call}));")
    return run_node(script, payload)


MODES = ["dance", "rehab", "fitness"]


@pytest.mark.parametrize("samples,offered,default", [
    ({"profiles": MODES, "profile_default": "fitness"}, MODES, "fitness"),
    ({"profiles": MODES, "profile_default": "rehab"}, MODES, "rehab"),                # the server's own default is followed
    ({"profiles": MODES, "profile_default": "gym"}, MODES, "fitness"),                # a default that is not offered is replaced
    ({"profiles": MODES}, MODES, "fitness"),                                          # no default named
    ({"profiles": ["dance", "rehab"]}, ["dance", "rehab"], "dance"),                  # no fitness on offer: the first mode
    ({"profiles": ["dance", "", 3, None, "rehab"]}, ["dance", "rehab"], "dance"),     # only names are modes
    ({}, [], None),                                                                   # an older server: no mode, no select
    ({"profiles": []}, [], None),
    ({"profiles": "rehab"}, [], None),
])
def test_AC_V21_the_page_offers_exactly_the_modes_api_samples_lists_and_starts_on_the_default(samples, offered, default):
    got = mode_page("({ offered: j.profilesOffered(payload), start: j.defaultProfile(payload) })", samples)
    assert got == {"offered": offered, "start": default}


def test_AC_V21_a_mode_is_shown_with_a_capital_and_sent_in_lower_case():
    assert mode_page("payload.map(j.profileLabel)", MODES) == ["Dance", "Rehab", "Fitness"]
    body = mode_page("a.analyseBody({ sample: 'x' }, { sample: 'y' }, 'template', payload)", "rehab")
    assert body["profile"] == "rehab"


def test_AC_V21_the_page_offers_what_the_real_api_samples_lists():
    listing = api._samples_listing()
    got = mode_page("({ offered: j.profilesOffered(payload), start: j.defaultProfile(payload) })", listing)
    assert got["offered"] == listing.get("profiles", [])      # none today on a server that does not know modes
    assert got["start"] == (listing["profile_default"] if got["offered"] else None)


@pytest.mark.parametrize("profile,carries", [("rehab", True), ("dance", True), ("fitness", True),
                                             (None, False), ("", False), (3, False)])
def test_AC_V21_the_request_carries_the_chosen_mode_and_no_profile_when_none_was_offered(profile, carries):
    body = mode_page("a.analyseBody({ sample: 'e' }, { upload: 't' }, 'template', payload)", profile)
    assert body["expected"] == {"sample": "e"} and body["follower"] == {"upload": "t"} and body["phrasing"] == "template"
    assert ("profile" in body) is carries
    assert (body["profile"] == profile) if carries else True


def test_AC_V21_a_request_for_a_server_without_modes_is_the_one_the_page_always_sent():
    both = mode_page("[a.analyseBody({ sample: 'e' }, { sample: 'f' }), a.analyseBody({ sample: 'e' }, { sample: 'f' }, 'local-llm', null)]", None)
    assert both == [{"expected": {"sample": "e"}, "follower": {"sample": "f"}, "phrasing": "template"},
                    {"expected": {"sample": "e"}, "follower": {"sample": "f"}, "phrasing": "local-llm"}]


def test_AC_V21_the_page_builds_the_request_only_through_the_shared_body():
    source = (ROOT / "web/api.js").read_text()
    assert "JSON.stringify(analyseBody(expected, follower, phrasing, profile))" in source
    assert "JSON.stringify({ expected, follower, phrasing })" not in source


@pytest.mark.parametrize("analysis,note", [
    ({"profile": "rehab"}, "Scored with rehab coaching rules."),
    ({"profile": "dance"}, "Scored with dance coaching rules."),
    ({"profile": "fitness"}, None),            # the standard mode is not announced
    ({}, None),                                # a document from before 1.7.0 is read as fitness
    ({"profile": ""}, None),
    ({"profile": 7}, None),
    (None, None),
])
def test_AC_V21_the_result_names_a_mode_other_than_fitness(analysis, note):
    assert mode_page("j.profileNote(payload)", analysis) == note


def test_AC_V21_no_mode_sentence_has_an_em_dash_an_en_dash_or_a_spaced_hyphen():
    notes = [mode_page("j.profileNote(payload)", {"profile": name}) for name in ("dance", "rehab")]
    assert not [n for n in notes if any(mark in n for mark in (chr(0x2014), chr(0x2013), " - "))]


# ----------------------------------------------------------------------------- AC-V22: each skeleton stands on the floor

ONE_MM = 0.001
GROUND_SCRIPT = (f'import {{ FLOOR_Y, groundClip, groundFrame, boundsOf }} from "{VIEWER_URL}";\n')


def stand(joints):
    """A 17 joint frame from {index: [x, y, z]}; every other joint is masked (null)."""
    return [joints.get(i) for i in range(17)]


def test_AC_V22_the_lowest_joint_of_a_frame_is_put_on_the_floor_and_x_and_z_are_left_alone():
    frame = stand({0: [0.01, 0.52, 0.03], 11: [-0.1, 0.0, 0.0], 12: [0.1, 0.0, 0.0], 15: [-0.12, -0.62, 0.05],
                   16: [0.13, -0.58, -0.04]})
    out = run_node(GROUND_SCRIPT + "console.log(JSON.stringify({ floor: FLOOR_Y, frame: groundFrame(payload) }));", frame)
    grounded = out["frame"]
    assert grounded[15][1] == pytest.approx(out["floor"], abs=ONE_MM)      # the lowest joint stands on the floor
    assert [round(j[1] - out["floor"], 6) for j in grounded if j] == [1.14, 0.62, 0.62, 0.0, 0.04]
    assert [j[0::2] for j in grounded if j] == [j[0::2] for j in frame if j]  # x and z untouched (hip midpoint stays at 0)
    assert [j is None for j in grounded] == [j is None for j in frame]        # a masked joint stays masked


def test_AC_V22_the_lowest_of_all_joints_decides_so_a_lying_pose_lies_on_the_floor():
    lying = stand({0: [0.0, -0.05, 0.9], 11: [-0.1, 0.0, 0.0], 12: [0.1, 0.0, 0.0], 15: [-0.1, 0.02, -0.8],
                   16: [0.1, 0.03, -0.8], 9: [-0.3, -0.31, 0.2]})                  # the left wrist is the lowest joint
    out = run_node(GROUND_SCRIPT + "console.log(JSON.stringify(groundFrame(payload)));", lying)
    assert min(j[1] for j in out if j) == pytest.approx(0.0, abs=ONE_MM)
    assert out[9][1] == pytest.approx(0.0, abs=ONE_MM) and out[15][1] > 0.3     # not the ankles


def test_AC_V22_the_body_does_not_jump_when_the_feet_trade_places():
    left_lower = stand({11: [-0.1, 0.0, 0.0], 12: [0.1, 0.0, 0.0], 15: [-0.1, -0.800, 0.0], 16: [0.1, -0.795, 0.0]})
    right_lower = stand({11: [-0.1, 0.0, 0.0], 12: [0.1, 0.0, 0.0], 15: [-0.1, -0.795, 0.0], 16: [0.1, -0.800, 0.0]})
    out = run_node(GROUND_SCRIPT + "console.log(JSON.stringify(payload.map(groundFrame)));", [left_lower, right_lower])
    hips = [frame[11][1] for frame in out]
    assert abs(hips[0] - hips[1]) < 0.01 and min(hips) == pytest.approx(0.8, abs=0.01)


def test_AC_V22_a_frame_with_no_joint_to_stand_on_is_returned_as_it_is():
    script = GROUND_SCRIPT + ("const none = Array(17).fill(null); const nan = Array(17).fill([0, NaN, 0]);\n"
                              "console.log(JSON.stringify({ none: groundFrame(none), nan: groundFrame(nan).map((j) => Number.isNaN(j[1])),"
                              " empty: groundFrame([]), clip: groundClip([]) }));")
    out = run_node(script, None)
    assert out["none"] == [None] * 17 and out["empty"] == [] and out["clip"] == []
    assert out["nan"] == [True] * 17            # a joint with no usable height decides nothing and is not moved


def real_replays():
    """Replays of a squat with a foot fault, a shallow squat and a yoga class against the squat (a different pose set)."""
    shallow = next(t["id"] for t in api._samples_listing()["followers"]
                   if t["set"] == "exercise" and t["angle"] == "front" and t["light"] == "good"
                   and t["faults"] and t["faults"][0]["type"] == "knees_shallow")
    foot = next(t["id"] for t in api._samples_listing()["followers"]
                if t["set"] == "exercise" and t["faults"] and t["faults"][0]["type"] == "foot_out")
    pairs = [("exercise", foot), ("exercise", shallow), ("part3-squat", "part2-class")]
    return [analysed(expected, follower)["replay"] for expected, follower in pairs]


def test_AC_V22_in_every_frame_each_skeletons_lowest_joint_is_within_1_mm_of_the_floor_and_the_hip_stays_centred():
    replays = real_replays()
    script = GROUND_SCRIPT + (
        "const lowest = (frame) => Math.min(...frame.filter(Boolean).map((j) => j[1]));\n"
        "const hipOff = (frame) => (frame[11] && frame[12]) ? Math.max(Math.abs(frame[11][0] + frame[12][0]),"
        " Math.abs(frame[11][2] + frame[12][2])) / 2 : 0;\n"
        "const out = payload.map((replay) => { const clips = { expected: groundClip(replay.expected), follower: groundClip(replay.follower) };\n"
        "  const frames = [...clips.expected, ...clips.follower];\n"
        "  const raw = [...replay.expected, ...replay.follower];\n"
        "  return { floor: FLOOR_Y, frames: frames.length, lowest: frames.map(lowest), hipOff: frames.map(hipOff),\n"
        "    wasOff: raw.map(lowest), bounds: boundsOf(clips), topY: Math.max(...frames.flat().filter(Boolean).map((j) => j[1])) }; });\n"
        "console.log(JSON.stringify(out));")
    out = run_node(script, replays)
    for replay, got in zip(replays, out):
        assert got["frames"] == len(replay["expected"]) + len(replay["follower"]) > 150
        assert all(abs(y - got["floor"]) <= ONE_MM for y in got["lowest"]), "every frame stands on the floor"
        assert max(got["hipOff"]) <= ONE_MM, "the hip midpoint stays at x = z = 0"
        assert max(got["wasOff"]) - min(got["wasOff"]) > 0.1, "the replay itself lifts the feet, which is what this fixes"
        # the camera target and the distance come from the grounded positions, not the hip-anchored ones
        assert got["bounds"]["centre"][1] == pytest.approx((got["floor"] + got["topY"]) / 2, abs=ONE_MM)


def test_AC_V22_the_camera_stands_where_the_bounding_sphere_fits_whole_from_every_preset():
    """The distance is radius over the sine of half the field of view, so the sphere's edge meets the view's edge and no
    joint is outside the view cone, however near the camera it is (the tangent left the nearer foot 0.4 px out, N4)."""
    script = GROUND_SCRIPT.replace("boundsOf }", "boundsOf, fitDistance, FOV_DEG }") + (
        "const half = (FOV_DEG / 2) * Math.PI / 180;\n"
        "const sphere = [0.5, 0.86, 1.4].map((r) => Math.asin(r / fitDistance(r)) - half);\n"
        "const dirs = [[0, 0, 1], [1, 0, 0], [0, Math.cos(0.02), Math.sin(0.02)]];\n"
        "const worst = payload.map((replay) => { const clips = { expected: groundClip(replay.expected), follower: groundClip(replay.follower) };\n"
        "  const { centre, radius } = boundsOf(clips); const d = fitDistance(radius);\n"
        "  return Math.max(...dirs.flatMap((dir) => { const cam = centre.map((c, i) => c + dir[i] * d);\n"
        "    const axis = centre.map((c, i) => c - cam[i]); const norm = (v) => Math.hypot(...v);\n"
        "    return [...clips.expected, ...clips.follower].flat().filter(Boolean).map((j) => { const v = j.map((x, i) => x - cam[i]);\n"
        "      return Math.acos(v.reduce((s, x, i) => s + x * axis[i], 0) / (norm(v) * norm(axis))); }); })) - half; });\n"
        "console.log(JSON.stringify({ sphere, worst }));")
    out = run_node(script, real_replays())
    assert all(abs(gap) < 1e-9 for gap in out["sphere"])                  # the sphere's edge is the view's edge
    assert all(gap <= 1e-9 for gap in out["worst"]), out["worst"]         # no joint of any replay is outside the view cone


def test_AC_V22_the_page_draws_the_grounded_clips_and_puts_the_grid_at_the_floor():
    source = (ROOT / "web/viewer.js").read_text()
    assert "clips.expected[frame]" in source and "clips.follower[followerFrame]" in source
    assert "replay.expected[frame]" not in source and "replay.follower[followerFrame]" not in source
    assert "boundsOf(clips)" in source and "boundsOf(next)" not in source
    assert "grid.position.set(0, FLOOR_Y - GRID_DROP, 0)" in source
