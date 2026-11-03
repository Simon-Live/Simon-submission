"""docs/specs/model-retarget.md: the node unit tests, the rest reader tool (AC-RT9), the fixtures and the file rules."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/part7/fixtures/skin"
TOOL = ROOT / "tools/rest_joints_from_glb.py"
NODE_TESTS = ["retarget.unit.test.mjs", "retarget.skin-math.unit.test.mjs"]
# Optional real model files (untrusted downloads, never committed): a folder laid out like the scratch models.
MODELS = Path(os.environ.get("SIMON_TEST_MODELS", "/nonexistent"))
UAL2 = MODELS / "quaternius-ual2/extracted/Universal Animation Library 2 [Standard]/Female Mannequin/Unreal-Godot/Mannequin_F.glb"
FIGURE = MODELS / "khronos-riggedfigure/RiggedFigure.glb"


def _tool():
    spec = importlib.util.spec_from_file_location("rest_joints_from_glb", TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rj = _tool()


@pytest.mark.parametrize("name", NODE_TESTS)
def test_node_unit_tests_pass(name):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--test", str(ROOT / "tests/part7" / name)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]


def _glb(nodes: list[dict], skins: list[dict] | None, scene_nodes: list[int]) -> bytes:
    doc = {"asset": {"version": "2.0"}, "nodes": nodes, "scenes": [{"nodes": scene_nodes}]}
    if skins is not None:
        doc["skins"] = skins
    body = json.dumps(doc).encode()
    body += b" " * (-len(body) % 4)
    return b"glTF" + struct.pack("<II", 2, 12 + 8 + len(body)) + struct.pack("<II", len(body), 0x4E4F534A) + body


def _canonical_glb(yaw_deg: float = 0.0) -> tuple[bytes, dict]:
    rest = json.loads((FIX / "rest-tpose.json").read_text())["bones"]
    names = list(rest)
    half = math.radians(yaw_deg) / 2
    qy = [0, math.sin(half), 0, math.cos(half)]
    root_matrix = [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1]  # Z up to Y up, as Khronos CesiumMan does
    # positions are stored in the Z-up frame so that the root matrix is what puts the model upright
    nodes = [{"name": "Z_UP", "matrix": root_matrix, "children": [1]}, {"name": "Armature", "rotation": qy, "children": list(range(2, 2 + len(names)))}]
    for n in names:
        x, y, z = rest[n]["head"]
        nodes.append({"name": n, "translation": [x, -z, y]})
    skin = {"joints": list(range(2, 2 + len(names)))}
    return _glb(nodes, [skin], [0]), rest


def test_the_tool_reads_matrices_and_prints_world_positions():
    data, rest = _canonical_glb()
    out = rj.rest_joints(data, "canonical", normalize=False, source="synthetic")
    assert out["schema"] == "simon.rest.v1" and out["fix"] == [0, 0, 0, 1]
    for name, want in rest.items():
        got = out["bones"][name]["head"]
        assert all(abs(a - b) < 1e-5 for a, b in zip(got, want["head"])), name
    assert out["bones"]["hips"]["tail"] == out["bones"]["spine"]["head"]
    assert out["bones"]["leftHand"]["tail"] is None
    w = out["bones"]["leftHand"]["world"]
    assert abs(math.sqrt(sum(c * c for c in w)) - 1) < 1e-5


def test_normalize_makes_up_y_and_left_x_for_a_model_that_faces_the_other_way():
    data, rest = _canonical_glb(yaw_deg=180)
    raw = rj.rest_joints(data, "canonical", normalize=False)
    assert raw["bones"]["leftUpperArm"]["head"][0] < 0
    out = rj.rest_joints(data, "canonical", normalize=True)
    for name in ("hips", "leftUpperArm", "rightFoot", "head"):
        want, got = rest[name]["head"], out["bones"][name]["head"]
        assert all(abs(a - b) < 1e-4 for a, b in zip(got, want)), name
    assert out["bones"]["leftUpperArm"]["head"][0] > 0
    assert out["fix"] != [0, 0, 0, 1]


def test_normalize_uprights_a_model_lying_on_its_back():
    data, rest = _canonical_glb()
    doc_nodes = [dict(n) for n in json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])["nodes"]]
    doc_nodes[0] = {**doc_nodes[0], "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}  # Z up left alone
    lying = _glb(doc_nodes, [{"joints": list(range(2, len(doc_nodes)))}], [0])
    out = rj.rest_joints(lying, "canonical", normalize=True)
    hips, head = out["bones"]["hips"]["head"], out["bones"]["head"]["head"]
    assert head[1] - hips[1] > 0.4 and abs(head[2] - hips[2]) < 1e-3
    assert out["bones"]["leftUpperArm"]["head"][0] > 0


@pytest.mark.parametrize("data,why", [
    (b"", "not a GLB"),
    (b"glTF" + b"\0" * 30, "JSON chunk"),
    (_glb([{"name": "a"}], None, [0]), "no skin"),
    (_glb([{"name": "a"}], [{"joints": [0]}], [0]), "mapped bones missing"),
])
def test_the_tool_exits_2_with_one_line_on_bad_input(tmp_path, data, why):
    f = tmp_path / "m.glb"
    f.write_bytes(data)
    r = subprocess.run([sys.executable, "-I", str(TOOL), str(f)], capture_output=True, text=True)
    assert r.returncode == 2 and r.stdout == ""
    assert why in r.stderr and len(r.stderr.strip().splitlines()) == 1


def test_the_tool_exits_2_for_a_missing_file_and_a_bad_map(tmp_path):
    r = subprocess.run([sys.executable, "-I", str(TOOL), str(tmp_path / "nope.glb")], capture_output=True, text=True)
    assert r.returncode == 2 and "rest_joints_from_glb:" in r.stderr
    data, _ = _canonical_glb()
    f = tmp_path / "m.glb"
    f.write_bytes(data)
    (tmp_path / "map.json").write_text("{not json")
    r = subprocess.run([sys.executable, "-I", str(TOOL), str(f), "--map", str(tmp_path / "map.json")], capture_output=True, text=True)
    assert r.returncode == 2


def test_the_tool_runs_end_to_end_and_prints_json(tmp_path):
    data, _ = _canonical_glb()
    f = tmp_path / "m.glb"
    f.write_bytes(data)
    r = subprocess.run([sys.executable, "-I", str(TOOL), str(f), "--normalize"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert set(json.loads(r.stdout)["bones"]) >= set(rj.REQUIRED)


def test_a_custom_map_replaces_the_preset(tmp_path):
    data, _ = _canonical_glb()
    mapping = {n: n for n in json.loads((FIX / "rest-tpose.json").read_text())["bones"]}
    mapping["leftHand"] = "ignored"
    out = rj.rest_joints(data, "canonical", name_map={k: v for k, v in mapping.items() if v != "ignored"})
    assert "leftHand" in out["bones"]
    with pytest.raises(rj.RestError, match="mapped bones missing"):
        rj.rest_joints(data, "ual")


def test_a_node_cycle_is_an_error():
    nodes = [{"name": "a", "children": [1]}, {"name": "b", "children": [0]}]
    with pytest.raises(rj.RestError, match="cycle"):
        rj.world_matrices(nodes)


@pytest.mark.skipif(not UAL2.exists(), reason="SIMON_TEST_MODELS does not hold the real models")
@pytest.mark.parametrize("path,preset,fixture", [(UAL2, "ual", "rest-ual2f.json"), (FIGURE, "riggedfigure", "rest-riggedfigure.json")])
def test_real_models_match_the_committed_dumps(path, preset, fixture):
    got = rj.rest_joints(path.read_bytes(), preset, normalize=True)["bones"]
    want = json.loads((FIX / fixture).read_text())["bones"]
    assert set(got) == set(want)
    for name, b in want.items():
        for k in ("head", "world"):
            assert all(abs(x - y) < 2e-6 for x, y in zip(got[name][k], b[k])), (name, k)


@pytest.mark.parametrize("name", ["rest-tpose.json", "rest-apose.json", "rest-ual2f.json", "rest-riggedfigure.json"])
def test_rest_fixtures_are_upright_left_x_and_have_every_required_bone(name):
    d = json.loads((FIX / name).read_text())
    assert d["schema"] == "simon.rest.v1"
    bones = d["bones"]
    assert set(rj.REQUIRED) <= set(bones)
    assert bones["leftUpperArm"]["head"][0] > bones["rightUpperArm"]["head"][0]
    assert bones["head"]["head"][1] > bones["hips"]["head"][1] > bones["leftFoot"]["head"][1]
    for b in bones.values():
        assert abs(math.sqrt(sum(c * c for c in b["world"])) - 1) < 1e-4


def test_the_replay_fixture_is_a_follower_track_without_video_or_identity():
    d = json.loads((FIX / "replay-fixture.json").read_text())
    assert len(d["follower"]) == 96 and len(d["joints"]) == 17
    assert set(d) == {"format", "source", "fps", "joints", "coordinate_frame", "follower"}
    assert all(len(f) == 17 and all(len(p) == 3 for p in f) for f in d["follower"])


def test_files_carry_no_dash_characters_and_stay_small():
    files = [ROOT / "web/skin" / n for n in ("quat.js", "retarget.js", "skin-math.js")]
    spec = ROOT / "docs/specs/model-retarget.md"  # docs/specs/ is not published to the client repo
    files += [TOOL, *([spec] if spec.is_file() else []), Path(__file__)]
    files += [ROOT / "tests/part7" / n for n in NODE_TESTS]
    for f in files:
        text = f.read_text()
        assert chr(0x2014) not in text and chr(0x2013) not in text, f.name
        assert len(text.splitlines()) < 800, f.name
