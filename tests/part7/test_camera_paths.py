"""Camera paths for the cinematic render (docs/specs/camera-path.md, AC-1 to AC-4)."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/camera_paths.py"
SAMPLES = ROOT / "docs/specs/camera-path-samples"
ANALYSIS = ROOT / "fixtures/input/analysis-timeline.json"
POSE = ROOT / "modules/part-2/fixtures/output/single/pose3d.json"

spec = importlib.util.spec_from_file_location("camera_paths", TOOL)
cp = importlib.util.module_from_spec(spec)
sys.modules["camera_paths"] = cp
spec.loader.exec_module(cp)


def small_pose(n: int = 4) -> dict[str, Any]:
    """A 2 s take at 2 frames a second: a person whose joints sit on a 1 m column around the origin."""
    names = ["nose", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_ankle", "right_ankle"]
    pts = [[0, 0.6, 0.1], [0.2, 0.5, 0], [-0.2, 0.5, 0], [0.4, 0.3, 0.1], [-0.4, 0.3, 0.1], [0.1, -0.9, 0], [-0.1, -0.9, 0]]
    return {"frames": [{"frame": i, "t_ms": i * 500.0, "people": [
        {"id": 0, "joints": {k: {"x": p[0] + 0.01 * i, "y": p[1], "z": p[2], "conf": 1.0} for k, p in zip(names, pts)}}]}
        for i in range(n)]}


def analysis(value: int = 70, joint: str | None = "elbow", side: str | None = "left", at: float = 1.0) -> dict[str, Any]:
    miss = {"joint": joint, "side": side, "at_s": at, "points": 10.0, "t_s": [at, at + 0.2]}
    return {"score": {"timeline": [
        {"t_s": [0, 1], "value": 95, "misses": [], "compared": True},
        {"t_s": [1, 2], "value": value, "misses": [miss] if value < 90 else [], "compared": True}]}}


def load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


# ----- AC-1 samples and determinism -----------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["orbit", "push-in", "bullet-time", "slow-motion"])
def test_the_samples_validate(name: str) -> None:
    cp.validate(load(SAMPLES / f"{name}.json"))


def test_the_samples_are_what_the_tool_makes_for_the_fixture_result() -> None:
    built = cp.build_all(load(ANALYSIS), load(POSE))
    assert sorted(built) == ["bullet-time", "orbit", "push-in", "slow-motion"]
    for name, doc in built.items():
        assert json.dumps(doc, indent=1) + "\n" == (SAMPLES / f"{name}.json").read_text(encoding="utf-8")


def test_two_builds_are_identical() -> None:
    a, b = cp.build_all(analysis(), small_pose()), cp.build_all(analysis(), small_pose())
    assert json.dumps(a) == json.dumps(b)


# ----- AC-2 interpolation ----------------------------------------------------------------------------------------------
def two_keys(ease: str) -> dict[str, Any]:
    return {"schema": cp.SCHEMA, "fps": 30, "duration_s": 2.0, "space": "pose", "keys": [
        {"t": 0, "position": [0, 0, 4], "target": [0, 0, 0], "fov_deg": 40, "ease": ease, "take_time": 0},
        {"t": 2, "position": [0, 2, 2], "target": [0, 0, 0], "fov_deg": 20, "ease": "linear", "take_time": 4}]}


@pytest.mark.parametrize("ease,mid", [("linear", 0.5), ("ease-in", 0.25), ("ease-out", 0.75), ("ease-in-out", 0.5)])
def test_the_midpoint_follows_the_easing(ease: str, mid: float) -> None:
    got = cp.sample(two_keys(ease), 1.0)
    assert got["position"] == pytest.approx([0, 2 * mid, 4 - 2 * mid])
    assert got["fov_deg"] == pytest.approx(40 - 20 * mid) and got["take_time"] == pytest.approx(4 * mid)


def test_key_times_give_key_values_and_outside_holds() -> None:
    path = two_keys("ease-in-out")
    assert cp.sample(path, 0)["position"] == [0, 0, 4] and cp.sample(path, 2)["position"] == [0, 2, 2]
    assert cp.sample(path, -3) == cp.sample(path, 0) and cp.sample(path, 99) == cp.sample(path, 2)


def test_a_path_without_take_time_plays_in_real_time() -> None:
    path = two_keys("linear")
    for k in path["keys"]:
        del k["take_time"]
    assert cp.sample(path, 1.0)["take_time"] == 1.0  # absent: real time from start_take_time (0)
    path["start_take_time"] = 3.0
    assert cp.sample(path, 1.5)["take_time"] == 4.5


# ----- AC-3 validation (negative assertions) --------------------------------------------------------------------------
def mutate(fn: Any) -> dict[str, Any]:
    p = copy.deepcopy(load(SAMPLES / "push-in.json"))
    fn(p)
    return p


@pytest.mark.parametrize("fn,word", [
    (lambda p: p.update(schema="x"), "schema"),
    (lambda p: p.update(space="world"), "space"),
    (lambda p: p.update(fps=0), "fps"),
    (lambda p: p.update(fps=2.5), "fps"),
    (lambda p: p.update(fps=True), "fps"),
    (lambda p: p.update(duration_s=0), "duration_s"),
    (lambda p: p.update(duration_s=float("nan")), "duration_s"),
    (lambda p: p.update(start_take_time=-1), "start_take_time"),
    (lambda p: p.update(keys=p["keys"][:1]), "keys must be"),
    (lambda p: p["keys"][0].update(t=1), "first key"),
    (lambda p: p["keys"][1].update(t=5), "last key"),
    (lambda p: p["keys"][1].update(t=0), "larger"),
    (lambda p: p["keys"][0].update(position=[0, 0]), "position"),
    (lambda p: p["keys"][0].update(target=[0, 0, "a"]), "target"),
    (lambda p: p["keys"][0].update(position=[99, 0, 0]), "position"),
    (lambda p: p["keys"][0].update(position=p["keys"][0]["target"]), "closer"),
    (lambda p: p["keys"][0].update(fov_deg=3), "fov_deg"),
    (lambda p: p["keys"][0].update(ease="bounce"), "ease"),
    (lambda p: p["keys"][0].pop("ease"), "ease"),
    (lambda p: p["keys"][0].update(take_time=1.0), "take_time must be on every key"),
    (lambda p: [k.update(take_time=-1) for k in p["keys"]], "take_time must be a number"),
    (lambda p: p.update(keys=[0, 1]), "not an object"),
])
def test_a_broken_path_is_refused_with_a_plain_line(fn: Any, word: str) -> None:
    with pytest.raises(cp.PathError) as err:
        cp.validate(mutate(fn))
    assert word in str(err.value)


def test_a_path_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(cp.PathError):
        cp.validate([1])


def test_many_problems_are_summarised() -> None:
    p = mutate(lambda p: p["keys"][0].update(position=1, target=2, fov_deg=0, ease="x", t=3))
    p.update(schema="x", space="y")
    with pytest.raises(cp.PathError, match="and \\d+ more"):
        cp.validate(p)


# ----- the worst moment -----------------------------------------------------------------------------------------------
def test_the_worst_moment_is_the_largest_miss_of_the_lowest_window() -> None:
    got = cp.worst_moment(load(ANALYSIS))
    assert got is not None and got["source"] == "timeline" and got["joint"] and got["t_s"] > 0


def test_a_flawless_take_has_no_worst_moment_and_only_an_orbit() -> None:
    flawless = {"score": {"timeline": [{"t_s": [0, 1], "value": 97, "misses": [], "compared": True}]}}
    assert cp.worst_moment(flawless) is None
    assert list(cp.build_all(flawless, small_pose())) == ["orbit"]


def test_without_a_timeline_the_fault_with_the_most_points_wins() -> None:
    doc = {"faults": [{"joint": "a", "at_s": 1.0, "points": 3}, {"joint": "b", "at_s": 2.0, "points": 9}]}
    assert cp.worst_moment(doc)["joint"] == "b"
    assert cp.worst_moment({"faults": [{"joint": "a", "at_s": 1.0}, {"joint": "b", "at_s": 2.0}]})["joint"] == "a"
    assert cp.worst_moment({"faults": []}) is None


def test_a_window_without_misses_but_a_low_value_gives_its_middle() -> None:
    doc = {"score": {"timeline": [{"t_s": [2, 4], "value": 60, "misses": [], "compared": True}]}}
    assert cp.worst_moment(doc) == {"t_s": 3.0, "joint": None, "side": None, "source": "timeline"}


def test_an_uncompared_window_is_not_the_worst() -> None:
    doc = analysis()
    doc["score"]["timeline"].append({"t_s": [2, 3], "value": 1, "misses": [], "compared": False})
    assert cp.worst_moment(doc)["t_s"] == 1.0


# ----- AC-4 the four shapes ---------------------------------------------------------------------------------------------
def test_the_orbit_closes_at_a_constant_radius() -> None:
    path = cp.orbit(cp.Take(small_pose()), 60, 8.0)
    first, last = path["keys"][0], path["keys"][-1]
    assert first["position"] == last["position"] and last["t"] == 8.0 and len(path["keys"]) == 181
    target = first["target"]
    radii = {round(math.dist(k["position"], target), 3) for k in path["keys"]}
    assert len(radii) == 1
    assert all(k["target"] == target and k["ease"] == "linear" for k in path["keys"])
    quarter = path["keys"][45]["position"]  # 90 degrees round: from in front (+z) to the subject's left (+x)
    assert quarter[0] - target[0] > 0.9 * math.dist(first["position"], target) * math.cos(math.radians(8))


def test_the_push_in_ends_close_to_the_joint_at_the_worst_moment() -> None:
    take = cp.Take(small_pose())
    worst = cp.worst_moment(analysis(joint="elbow", side="left", at=1.0))
    path = cp.push_in(take, worst, 60)
    end = path["keys"][-1]
    joint = take.at(1.0)["left_elbow"]
    assert end["target"] == cp._r(joint) and math.dist(end["position"], joint) == pytest.approx(cp.CLOSE_M, abs=1e-3)
    assert end["position"][0] > joint[0]  # the left joint is shot from the subject's left
    assert path["keys"][0]["ease"] == "ease-in-out" and path["start_take_time"] == 0  # 1.0 s - 6 s is below 0
    assert math.dist(path["keys"][0]["position"], path["keys"][0]["target"]) > math.dist(end["position"], end["target"])


def test_the_push_in_starts_the_take_so_that_it_ends_on_the_worst_moment() -> None:
    long = {"frames": [{"frame": i, "t_ms": i * 1000.0, "people": small_pose(1)["frames"][0]["people"]} for i in range(12)]}
    path = cp.push_in(cp.Take(long), {"t_s": 9.0, "joint": "nose", "side": None}, 60)
    assert path["start_take_time"] + path["duration_s"] == 9.0


def test_a_joint_the_pose_lacks_aims_at_the_body_and_an_unsided_name_uses_both_sides() -> None:
    take = cp.Take(small_pose())
    assert take.joint(1.0, "knee", None) is None and take.joint(1.0, None, None) is None
    mid = take.joint(1.0, "elbow", None)
    assert mid[0] == pytest.approx(0.01 * 2, abs=1e-6) and mid[1] == pytest.approx(0.3)
    path = cp.push_in(take, {"t_s": 1.0, "joint": "knee", "side": None}, 60)
    cp.validate(path)


def test_bullet_time_holds_take_time_at_the_worst_moment_while_t_advances() -> None:
    take = cp.Take(small_pose())
    path = cp.bullet_time(take, {"t_s": 1.5, "joint": "elbow", "side": "right"}, 60)
    keys = path["keys"]
    assert {k["take_time"] for k in keys} == {1.5} and path["start_take_time"] == 1.5
    assert keys[-1]["t"] == 6.0 and len({k["t"] for k in keys}) == len(keys)
    spans = {round(math.dist(k["position"], k["target"]), 3) for k in keys}
    assert len(spans) == 1  # an arc, not a move in or out
    arc = [math.degrees(math.atan2(k["position"][0] - k["target"][0], k["position"][2] - k["target"][2])) for k in keys]
    assert arc[0] == pytest.approx(-70, abs=0.1) and arc[-1] == pytest.approx(110, abs=0.1)
    cp.validate(path, take.end_s)


def test_slow_motion_advances_the_take_at_a_quarter_of_render_time() -> None:
    long = {"frames": [{"frame": i, "t_ms": i * 1000.0, "people": small_pose(1)["frames"][0]["people"]} for i in range(12)]}
    take = cp.Take(long)
    path = cp.slow_motion(take, {"t_s": 8.0, "joint": "nose", "side": None}, 60)
    keys = path["keys"]
    for a, b in zip(keys, keys[1:]):
        assert (b["take_time"] - a["take_time"]) / (b["t"] - a["t"]) == pytest.approx(0.25, abs=1e-3)
    assert cp.sample(path, 4.0)["take_time"] == pytest.approx(8.0, abs=1e-3)  # the worst moment, two thirds in
    assert keys[0]["take_time"] == path["start_take_time"]
    cp.validate(path, take.end_s)


def test_slow_motion_near_the_end_of_a_take_stays_inside_it() -> None:
    take = cp.Take(small_pose())  # 1.5 s long
    path = cp.slow_motion(take, {"t_s": 99.0, "joint": None, "side": None}, 60)
    assert path["keys"][-1]["take_time"] <= take.end_s + 1e-3 and path["keys"][0]["take_time"] >= 0
    cp.validate(path, take.end_s)


def test_a_worst_moment_past_the_pose_is_held_at_its_last_frame() -> None:
    path = cp.bullet_time(cp.Take(small_pose()), {"t_s": 99.0, "joint": None, "side": None}, 60)
    assert path["keys"][-1]["take_time"] == pytest.approx(1.5)


# ----- take_time must stay inside the take (negative assertions) -----------------------------------------------------------
def test_a_take_time_beyond_the_take_is_refused_and_inside_it_is_not() -> None:
    path = two_keys("linear")  # take_time 0 to 4
    cp.validate(path, 4.0)
    cp.validate(path)  # no take length given: not checked
    with pytest.raises(cp.PathError, match="take_time reaches 4 s but the take is 3 s"):
        cp.validate(path, 3.0)


def test_a_real_time_path_longer_than_the_take_is_refused() -> None:
    path = mutate(lambda p: None)  # push-in: start_take_time 1.0667, 6 s long
    cp.validate(path, 7.07)
    with pytest.raises(cp.PathError, match="take_time reaches"):
        cp.validate(path, 5.0)


def test_an_orbit_longer_than_the_take_is_refused_by_build() -> None:
    with pytest.raises(cp.PathError, match="take_time reaches"):
        cp.build_all(analysis(), small_pose(), orbit_s=8.0)  # the take is 1.5 s
    assert cp.build_all(analysis(), small_pose())["orbit"]["duration_s"] == 1.5


# ----- the pose reader ---------------------------------------------------------------------------------------------------
def test_a_person_id_that_is_absent_is_refused() -> None:
    with pytest.raises(cp.PathError, match="no frames"):
        cp.Take(small_pose(), person=7)
    assert len(cp.Take(small_pose(), person="0").frames) == 4


# ----- the command line ------------------------------------------------------------------------------------------------
def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=60)


def test_build_writes_four_files_that_validate_and_validate_exits_0(tmp_path: Path) -> None:
    done = run("build", "--analysis", str(ANALYSIS), "--pose3d", str(POSE), "--out", str(tmp_path))
    assert done.returncode == 0, done.stderr
    files = sorted(tmp_path.glob("*.json"))
    assert [f.name for f in files] == ["bullet-time.json", "orbit.json", "push-in.json", "slow-motion.json"]
    assert run("validate", *map(str, files)).returncode == 0
    assert run("validate", "--take-duration", "7.0667", *map(str, files)).returncode == 0
    short = run("validate", "--take-duration", "3", *map(str, files))
    assert short.returncode == 2 and "take_time reaches" in short.stderr


def test_a_flawless_take_says_so_on_stderr(tmp_path: Path) -> None:
    a, p = tmp_path / "a.json", tmp_path / "p.json"
    a.write_text(json.dumps({"score": {"timeline": [{"t_s": [0, 1], "value": 99, "misses": [], "compared": True}]}}))
    p.write_text(json.dumps(small_pose()))
    done = run("build", "--analysis", str(a), "--pose3d", str(p), "--out", str(tmp_path / "o"))
    assert done.returncode == 0 and "no worst moment" in done.stderr
    assert [f.name for f in (tmp_path / "o").glob("*.json")] == ["orbit.json"]


def test_bad_input_is_exit_2_with_one_line(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    for args in (("validate", str(bad)), ("validate", str(tmp_path / "none.json")),
                 ("build", "--analysis", str(ANALYSIS), "--pose3d", str(bad), "--out", str(tmp_path / "o"))):
        done = run(*args)
        assert done.returncode == 2 and done.stderr.startswith("camera_paths:") and done.stderr.count("\n") == 1
