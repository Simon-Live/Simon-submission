"""TICKET-110: simon.animation/1 sample entries become simon.animation.v1 for Part 5."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from part7 import animation_format, modules, sections
from part7.parts import p5_analyse

SAMPLE = Path(__file__).parent / "fixtures" / "input" / "animation-squat-sample.json"
STAGING = Path.home() / ".local" / "state" / "simon-part-7" / "staging" / "catalog"
EXERCISE = ("exercise", "exercise_45_good_08_trunk_lean-center+arms_wider-right")


def _sample() -> dict[str, Any]:
    return json.loads(SAMPLE.read_text())


def _convert(doc: dict[str, Any]) -> dict[str, Any]:
    return json.loads(animation_format.to_v1(json.dumps(doc).encode()))


def test_sample_becomes_v1() -> None:
    src = _sample()
    out = _convert(src)
    assert out["format"] == "simon.animation.v1" and out["fps"] == 30.0
    assert out["joints"] == list(animation_format.JOINTS) and out["coordinate_frame"]["y"] == "world_up"
    assert len(out["frames"]) == len(src["frames"])
    first, joint = out["frames"][0], src["frames"][0]["people"][0]["joints"]["left_knee"]
    assert first["joints"]["left_knee"] == [joint["x"], joint["y"], joint["z"]] and first["conf"]["left_knee"] == joint["conf"]
    assert [f["t"] for f in out["frames"]] == [f["t_ms"] / 1000 for f in src["frames"]]


def test_unseen_joints_are_null() -> None:
    src = _sample()
    joints = src["frames"][1]["people"][0]["joints"]
    joints["nose"]["conf"] = 0
    del joints["left_wrist"]["x"]
    del joints["right_wrist"]
    out = _convert(src)["frames"][1]
    for name in ("nose", "left_wrist", "right_wrist"):
        assert out["joints"][name] is None and out["conf"][name] == 0.0
    assert out["joints"]["left_knee"] is not None


def test_person_is_first_or_by_id() -> None:
    src = _sample()
    for fr in src["frames"]:
        other = copy.deepcopy(fr["people"][0])
        other["id"] = 7
        for j in other["joints"].values():
            j["x"] += 1
        fr["people"].append(other)
    base = src["frames"][0]["people"][0]["joints"]["nose"]["x"]
    assert _convert(src)["frames"][0]["joints"]["nose"][0] == base
    got = json.loads(animation_format.to_v1(json.dumps(src).encode(), person_id=7))
    assert got["frames"][0]["joints"]["nose"][0] == base + 1


def test_v1_and_other_inputs_are_byte_identical() -> None:
    v1 = b'{"format": "simon.animation.v1", "frames": []}'
    assert animation_format.to_v1(v1) == v1
    for raw in (b"not json", b"[1]", b'{"format":"simon.skeleton.v1"}', b'{"schema":"other/1"}'):
        assert animation_format.to_v1(raw) == raw


def test_converted_sample_cuts_to_a_section() -> None:
    out = sections.cut(animation_format.to_v1(SAMPLE.read_bytes()), {"start_ms": 0, "end_ms": 1000, "index": 1, "count": 1})
    assert json.loads(out)["format"] == "simon.animation.v1"


def test_part5_doctor_accepts_the_converted_sample(tmp_path: Path) -> None:
    lk = modules.load()
    if not (lk.path("5") / "part5").is_dir():
        pytest.skip("Part 5 submodule not checked out")
    path = tmp_path / "expected.json"
    path.write_bytes(animation_format.to_v1(SAMPLE.read_bytes()))
    step = p5_analyse.doctor(path, tmp_path, consumer="part5", lock=lk)
    assert step["exit"] == 0, step


def _as_sample(v1: dict[str, Any]) -> dict[str, Any]:
    """A Part 4 v1 clip written the way the sample entries write it (simon.animation/1)."""
    frames = []
    for i, fr in enumerate(v1["frames"]):
        joints = {n: {"x": p[0], "y": p[1], "z": p[2], "conf": 1.0} for n, p in fr["joints"].items() if p}
        frames.append({"frame": i, "t_ms": fr["t"] * 1000, "interpolated": False, "people": [{"id": 0, "joints": joints}]})
    return {"schema": "simon.animation/1", "joints": v1["joints"], "fps": v1["fps"], "frames": frames}


def test_real_part5_analyse_on_a_converted_sample(tmp_path: Path) -> None:
    lk = modules.load()
    base = lk.path("5") / "fixtures" / "input"
    follower = base / "followers" / EXERCISE[0] / EXERCISE[1] / "skeleton.json"
    expected = base / "expected" / EXERCISE[0] / "animation.json"
    if not follower.is_file() or not expected.is_file() or not (lk.path("5") / "part5").is_dir():
        pytest.skip("Part 5 submodule not checked out")
    v1 = json.loads(expected.read_text())
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(_as_sample(v1)))
    converted = tmp_path / "converted.json"
    converted.write_bytes(animation_format.to_v1(sample.read_bytes()))
    _, analysis, code, notes = p5_analyse.run(converted, follower, tmp_path / "w", lock=lk)
    assert code == "ok", notes
    _, plain, plain_code, _ = p5_analyse.run(expected, follower, tmp_path / "p", lock=lk)
    assert plain_code == "ok"
    assert json.loads(analysis.read_text())["score"] == json.loads(plain.read_text())["score"]


def test_sample_without_conversion_is_what_part5_rejected(tmp_path: Path) -> None:
    lk = modules.load()
    if not (lk.path("5") / "part5").is_dir():
        pytest.skip("Part 5 submodule not checked out")
    path = tmp_path / "expected.json"
    path.write_bytes(SAMPLE.read_bytes())
    assert p5_analyse.doctor(path, tmp_path, consumer="part5", lock=lk)["exit"] != 0


@pytest.mark.skipif(not STAGING.is_dir(), reason="no staging catalog on this host")
def test_every_staging_library_animation_is_handled() -> None:
    seen = 0
    for path in sorted(STAGING.glob("*/animation.json")):
        data = path.read_bytes()
        doc = json.loads(data)
        out = animation_format.to_v1(data)
        if doc.get("format") == "simon.animation.v1":
            assert out == data, path
        else:
            assert doc.get("schema") == "simon.animation/1", (path, doc.get("format"), doc.get("schema"))
            conv = json.loads(out)
            assert conv["format"] == "simon.animation.v1" and len(conv["frames"]) == len(doc["frames"]), path
            assert any(j is not None for fr in conv["frames"] for j in fr["joints"].values()), path
        seen += 1
    assert seen >= 1


def test_names_outside_the_17_are_dropped() -> None:
    src = _sample()
    src["frames"][0]["people"][0]["joints"]["pelvis"] = {"x": 0, "y": 0, "z": 0, "conf": 1}
    assert set(_convert(src)["frames"][0]["joints"]) == set(animation_format.JOINTS)


@pytest.mark.skipif(not STAGING.is_dir(), reason="no staging catalog on this host")
def test_part5_doctor_accepts_every_converted_staging_sample(tmp_path: Path) -> None:
    lk = modules.load()
    if not (lk.path("5") / "part5").is_dir():
        pytest.skip("Part 5 submodule not checked out")
    for path in sorted(STAGING.glob("*/animation.json")):
        if json.loads(path.read_bytes()).get("format") == "simon.animation.v1":
            continue
        (tmp_path / "expected.json").write_bytes(animation_format.to_v1(path.read_bytes()))
        assert p5_analyse.doctor(tmp_path / "expected.json", tmp_path, consumer="part5", lock=lk)["exit"] == 0, path
