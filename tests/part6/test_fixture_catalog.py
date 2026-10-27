"""fixtures/make_catalog.py and the shipped fixtures/output/catalog (AC-003)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from part6 import __main__ as cli
from part6 import motion, processor, validate

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "fixtures" / "output" / "catalog"
EXPECTED = {
    "squat": ("Squat", "exercise", 10000, 3, ["start", "bottom", "top"],
              "Bodyweight squat, three repetitions."),
    "forward-lunge": ("Forward lunge", "exercise", 12000, 4, ["start", "bottom", "end"],
                      "Step forward and lower, alternating legs, four repetitions."),
    "jumping-jack": ("Jumping jack", "exercise", 8000, 8, ["start", "open", "end"],
                     "Arms and legs open and close, eight repetitions."),
    "side-step": ("Side step", "dance", 8000, 8, ["start", "out", "end"],
                  "Step to each side in turn with arms swinging, eight steps."),
    "arm-wave": ("Arm wave", "dance", 8000, 4, ["start", "peak", "end"],
                 "Both arms wave overhead, four waves."),
    "hip-twist": ("Hip twist", "dance", 8000, 8, ["start", "twist", "end"],
                  "Twist the hips left and right with bent knees, eight twists."),
}


def load(entry, name):
    return json.loads((CATALOG / entry / name).read_text())


def generator():
    path = ROOT / "fixtures" / "make_catalog.py"
    spec = importlib.util.spec_from_file_location("make_catalog", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(root):
    return {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def test_validate_exits_zero_on_the_shipped_catalog(capsys):
    assert cli.main(["validate", str(CATALOG)]) == 0
    assert json.loads(capsys.readouterr().out) == {"entries": 6, "invalid": 0}


def test_three_exercises_and_three_dances():
    manifests = [load(e, "manifest.json") for e in EXPECTED]
    assert sorted(m["category"] for m in manifests) == ["dance"] * 3 + ["exercise"] * 3
    assert sorted(p.name for p in CATALOG.iterdir()) == sorted(EXPECTED)


@pytest.mark.parametrize("entry", EXPECTED)
def test_manifest_matches_the_locked_table(entry):
    name, category, duration_ms, _, _, description = EXPECTED[entry]
    assert load(entry, "manifest.json") == {
        "id": entry, "name": name, "video_uri": None, "keyframes": "keyframes.json",
        "skeleton": "skeleton.json", "animation": "animation.json",
        "created_at": "2026-10-27T00:00:00Z", "schema_version": 1, "category": category,
        "description": description, "thumbnail": "thumbnail.svg", "duration_ms": duration_ms,
        "files_source": "fixture"}


@pytest.mark.parametrize("entry", EXPECTED)
def test_files_present_and_no_video(entry):
    names = sorted(p.name for p in (CATALOG / entry).iterdir())
    assert names == ["animation.json", "keyframes.json", "manifest.json", "skeleton.json",
                     "thumbnail.svg"]


@pytest.mark.parametrize("entry", EXPECTED)
def test_keyframes_reps_and_marks(entry):
    _, _, duration_ms, reps, marks, _ = EXPECTED[entry]
    kf = load(entry, "keyframes.json")
    assert kf["video"] is None and kf["fps"] == 30.0 and kf["analysis_fps"] == 30.0
    assert kf["quality"] == {"verdict": "fine"}
    repetitions = kf["people"][0]["repetitions"]
    assert len(repetitions) == reps
    for rep in repetitions:
        assert rep["movement"] == entry
        assert [m["name"] for m in rep["keyframes"]] == marks
    if entry != "squat":
        length = duration_ms / reps
        assert [m["t_ms"] for m in repetitions[1]["keyframes"]] == [
            round(length), round(length * 1.5), round(length * 2)]


def test_squat_marks_use_the_input_fixture_timing():
    reps = load("squat", "keyframes.json")["people"][0]["repetitions"]
    assert [[m["t_ms"] for m in r["keyframes"]] for r in reps] == [
        [500, 2000, 3500], [3500, 5000, 6500], [6500, 8000, 9500]]
    assert reps[0]["keyframes"][1]["frame"] == 60


@pytest.mark.parametrize("entry", EXPECTED)
def test_rates_and_frame_counts(entry):
    duration_ms = EXPECTED[entry][2]
    animation, skeleton = load(entry, "animation.json"), load(entry, "skeleton.json")
    assert animation["fps"] == 30.0 and len(animation["frames"]) == duration_ms * 30 // 1000
    assert len(skeleton["frames"]) == -(-len(animation["frames"]) // 2)
    assert skeleton["schema"] == "simon.skeleton/1" and animation["schema"] == "simon.animation/1"


@pytest.mark.parametrize("entry", EXPECTED)
def test_bone_length_variation_under_one_percent(entry):
    lengths = [processor._bone_lengths(f["people"][0]["joints"])
               for f in load(entry, "animation.json")["frames"]]
    for bone in lengths[0]:
        values = [frame[bone] for frame in lengths]
        assert (max(values) - min(values)) / (sum(values) / len(values)) < 0.01, (entry, bone)


@pytest.mark.parametrize("entry", EXPECTED)
def test_each_movement_actually_moves(entry):
    frames = load(entry, "animation.json")["frames"]
    assert len({json.dumps(f["people"][0]["joints"]) for f in frames}) > 10


def test_squat_equals_the_input_fixture():
    inputs = ROOT / "fixtures" / "input"
    for name in ("animation.json", "skeleton.json"):
        expected = json.loads((inputs / name).read_text())["frames"]
        assert load("squat", name)["frames"] == expected


@pytest.mark.parametrize("entry", EXPECTED)
def test_thumbnail_is_the_two_colour_drawing(entry):
    svg = (CATALOG / entry / "thumbnail.svg").read_text()
    assert svg.count("<line") == 16 and svg.count("<circle") == 17 and "<text" not in svg


def test_rerunning_the_generator_changes_nothing(tmp_path):
    generator().build(tmp_path / "again")
    assert tree(tmp_path / "again") == tree(CATALOG)


def test_generator_replaces_an_existing_entry_and_leaves_no_temp_folder(tmp_path):
    out = tmp_path / "out"
    (out / "squat").mkdir(parents=True)
    (out / "squat" / "stale.txt").write_text("old")
    ids = generator().build(out)
    assert ids == list(EXPECTED) and not (out / "squat" / "stale.txt").exists()
    assert not [p for p in out.iterdir() if p.name.startswith(".")]


def test_ids_match_the_pattern_and_the_family_table():
    for entry in EXPECTED:
        assert re.match(validate.ID_RE, entry) and entry in motion.FAMILIES
