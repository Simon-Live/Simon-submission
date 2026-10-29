"""The page's pure logic, run in Node against the real payload (docs/specs/viewer.md, AC-V01 to AC-V04).

`web/joints.js` (fallback mapping, jump target, highlight window) and `Playback` in `web/viewer.js`
have no DOM, so Node imports them directly. The producer's own mapping is the reference
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
