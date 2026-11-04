"""fixtures/make_catalog.py and the shipped fixtures/output/catalog (AC-003, AC-C13)."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from part6 import __main__ as cli
from part6 import formats, motion, processor, validate

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


PART4_IDS = ["part4-squat", "part4-step-touch"]
ALL_IDS = list(EXPECTED) + PART4_IDS
# sha256 of the Phase 1 shared files before the catalog gained provenance: they must not change.
PHASE1_SHA256 = {
    "arm-wave": ("8dea0492f798a51876cedd82ced994a2dcbf6fb656a3d0800a54cd1691395810",
                 "7e85a37d89de50a1292469ff028c285921c43c997c0350c140e1a22324189d87",
                 "65dd634033c48529686f955517755cac7b9cca0fad0e76e300d2f06d5b5c9723"),
    "forward-lunge": ("9a0cdcd2b48dac4322dac118bdfef94f689b3e7c8e85f9b88105fbd4dfa6d84e",
                      "71064bb687b0ebaef910fe4c870362a10fab1ac45699395504ab5931e97ab3d0",
                      "c001c467ade3a4d6b8e6862ec65f8ff1500a66964fbfa13e168bb3b49fe321e3"),
    "hip-twist": ("b846d3411d4f0c580fe4ce7002b1e603ce54decc883ba33b0703f452ce240baf",
                  "c63c9e96b365e2669742398e5abd517857ea08b85f9d5a35ec0ef03250f0e273",
                  "8b76066e644dd577ffb20d10fcf3d7ee7063d9a198c37977d8336d47fb8e6f85"),
    "jumping-jack": ("408467b501cf120b832bc93ff80a7444a3dfd6a7bb4589054432517a78ffd12b",
                     "72d0d5b3376de21d61f9ef8df4b0fac830b72aa339163591690cb129c7250fa5",
                     "1a094538e43c151b80355f1e62c6aced3d0f2d637f032f3e32a1fd78849e4624"),
    "side-step": ("14ab2f81964e2e8708886dd253119d929fe21d6f054205d37561bfa0d08e75da",
                  "2b1f0a00f799ae2830d9762abfc91a426adfa94a3c498db4c520fe3ee695c725",
                  "4e4abf31a409413bd8117fd0b454f21677bb6b71cbd04bae8db56c1f34160c5d"),
    "squat": ("ff1cf806086c5f314bdf964d05bb241cbf2efb4ee470e3b52292900696722eb0",
              "319b301c2ade36156ed58a6f9b29778411762d7a949b05eb9fc30faa09e43f89",
              "8573fd8fe4417dfa53dd489e2911f0dc8cb803f02999d66f678bfc84aa0721b6"),
}    # animation.json, keyframes.json, skeleton.json


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
    assert json.loads(capsys.readouterr().out) == {"entries": 8, "invalid": 0}


def test_four_exercises_and_four_dances():
    manifests = [load(e, "manifest.json") for e in ALL_IDS]
    assert sorted(m["category"] for m in manifests) == ["dance"] * 4 + ["exercise"] * 4
    assert sorted(p.name for p in CATALOG.iterdir()) == sorted(ALL_IDS)


def expected_provenance(entry):
    """What the manifest of a Phase 1 entry must say about its three files."""
    return {kind: {"part": 6, "format": fmt, "detected_by": how,
                   "sha256": hashlib.sha256((CATALOG / entry / f"{kind}.json").read_bytes()).hexdigest(),
                   "bytes": (CATALOG / entry / f"{kind}.json").stat().st_size}
            for kind, fmt, how in (("keyframes", "simon.keyframes/part1", "shape"),
                                   ("skeleton", "simon.skeleton/1", "version"),
                                   ("animation", "simon.animation.v1", "version"))}


@pytest.mark.parametrize("entry", EXPECTED)
def test_manifest_matches_the_locked_table(entry):
    name, category, duration_ms, _, _, description = EXPECTED[entry]
    assert load(entry, "manifest.json") == {
        "id": entry, "name": name, "video_uri": None, "keyframes": "keyframes.json",
        "skeleton": "skeleton.json", "animation": "animation.json",
        "created_at": "2026-10-27T00:00:00Z", "schema_version": 1, "category": category,
        "description": description, "thumbnail": "thumbnail.svg", "duration_ms": duration_ms,
        "files_source": "fixture", "provenance": expected_provenance(entry)}


@pytest.mark.parametrize("entry", EXPECTED)
def test_phase_1_keyframes_and_skeleton_are_byte_identical_to_phase_1(entry):
    # animation.json is simon.animation.v1 since TICKET-031, so its Phase 1 hash is not pinned
    got = tuple(hashlib.sha256((CATALOG / entry / f"{kind}.json").read_bytes()).hexdigest()
                for kind in ("keyframes", "skeleton"))
    assert got == PHASE1_SHA256[entry][1:]


@pytest.mark.parametrize("entry", ALL_IDS)
def test_every_fixture_has_the_v1_manifest_fields_and_no_visitor_flag(entry):
    manifest = load(entry, "manifest.json")
    assert "visitor" not in manifest and manifest["files_source"] == "fixture"
    assert validate.check_manifest(manifest, entry) == []
    assert set(manifest["provenance"]) == {"keyframes", "skeleton", "animation"}


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
    assert skeleton["schema"] == "simon.skeleton/1" and animation["format"] == "simon.animation.v1"


@pytest.mark.parametrize("entry", EXPECTED)
def test_bone_length_variation_under_one_percent(entry):
    lengths = [processor._bone_lengths({n: dict(zip("xyz", pos)) for n, pos in f["joints"].items()})
               for f in load(entry, "animation.json")["frames"]]
    for bone in lengths[0]:
        values = [frame[bone] for frame in lengths]
        assert (max(values) - min(values)) / (sum(values) / len(values)) < 0.01, (entry, bone)


@pytest.mark.parametrize("entry", EXPECTED)
def test_each_movement_actually_moves(entry):
    frames = load(entry, "animation.json")["frames"]
    assert len({json.dumps(f["joints"]) for f in frames}) > 10


def test_squat_equals_the_input_fixture():
    inputs = ROOT / "fixtures" / "input"
    skeleton = json.loads((inputs / "skeleton.json").read_text())["frames"]
    assert load("squat", "skeleton.json")["frames"] == skeleton
    animation = json.loads((inputs / "animation.json").read_text())
    assert load("squat", "animation.json") == processor.animation_v1(animation)


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
    assert ids == ALL_IDS and not (out / "squat" / "stale.txt").exists()
    assert not [p for p in out.iterdir() if p.name.startswith(".")]


def test_ids_match_the_pattern_and_the_family_table():
    for entry in ALL_IDS:
        assert re.match(validate.ID_RE, entry)
    for entry in EXPECTED:
        assert entry in motion.FAMILIES


def test_the_shipped_catalog_holds_eight_entries_two_of_them_from_part_4():
    assert len(list(CATALOG.iterdir())) == 8
    assert {load(e, "manifest.json")["provenance"]["animation"]["part"] for e in ALL_IDS} == {4, 6}


@pytest.mark.parametrize("entry", ALL_IDS)
def test_every_fixture_reads_through_the_formats_readers(entry):
    for kind in formats.KINDS:
        formats.read(kind, load(entry, f"{kind}.json"), f"{kind}.json")


# the conformance entries (AC-C16): fixtures/conformance/make_entries.py and entries/

CONFORMANCE = ROOT / "fixtures" / "conformance" / "entries"
CONFORMANCE_BY_SOURCE = {
    "fixture": ["conf-fixture-part4", "conf-fixture-part6"],
    "mock": ["conf-mock-a", "conf-mock-b"],
    "import": ["conf-import-part4", "conf-import-skeleton"],
    "processor": ["conf-processor-fake", "conf-processor-v1"],
}


def entries_generator():
    path = ROOT / "fixtures" / "conformance" / "make_entries.py"
    spec = importlib.util.spec_from_file_location("make_entries", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def conf(entry):
    return json.loads((CONFORMANCE / entry / "manifest.json").read_text())


def test_validate_exits_zero_on_the_conformance_entries(capsys):
    assert cli.main(["validate", str(CONFORMANCE)]) == 0
    assert json.loads(capsys.readouterr().out) == {"entries": 8, "invalid": 0}


def test_two_entries_per_files_source():
    found = {}
    for folder in sorted(CONFORMANCE.iterdir()):
        found.setdefault(conf(folder.name)["files_source"], []).append(folder.name)
    assert found == CONFORMANCE_BY_SOURCE


def test_conformance_entry_ids_are_the_ids_make_entries_writes():
    assert sorted(entries_generator().IDS) == sorted(p.name for p in CONFORMANCE.iterdir())


def test_the_import_entry_without_an_animation_says_null():
    manifest = conf("conf-import-skeleton")
    assert manifest["animation"] is None and "animation" not in manifest["provenance"]
    assert not (CONFORMANCE / "conf-import-skeleton" / "animation.json").exists()
    assert manifest["provenance"]["keyframes"]["part"] is None    # imported without a part
    assert manifest["provenance"]["skeleton"]["format"] == "simon.skeleton/1"


@pytest.mark.parametrize("entry,formats_by_kind", [
    ("conf-fixture-part6", {"keyframes": "simon.keyframes/part1", "skeleton": "simon.skeleton/1",
                            "animation": "simon.animation/1"}),
    ("conf-fixture-part4", {"keyframes": "simon.keyframes.v1", "skeleton": "simon.skeleton.v1",
                            "animation": "simon.animation.v1"}),
    ("conf-mock-a", {"keyframes": "simon.keyframes/part1", "skeleton": "simon.skeleton/1",
                     "animation": "simon.animation/1"}),
    ("conf-import-part4", {"keyframes": "simon.keyframes.v1", "skeleton": "simon.skeleton.v1",
                           "animation": "simon.animation.v1"}),
    ("conf-processor-fake", {"keyframes": "simon.keyframes.v1", "skeleton": "simon.skeleton.v1",
                             "animation": "simon.animation.v1"}),
    ("conf-processor-v1", {"skeleton": "simon.skeleton/1", "animation": "simon.animation.v1"})])
def test_provenance_formats(entry, formats_by_kind):
    provenance = conf(entry)["provenance"]
    assert {k: v["format"] for k, v in provenance.items()} == formats_by_kind
    for kind, record in provenance.items():
        raw = (CONFORMANCE / entry / f"{kind}.json").read_bytes()
        assert record["sha256"] == hashlib.sha256(raw).hexdigest() and record["bytes"] == len(raw)


def test_conformance_entries_are_static_data_never_counted_by_the_cap():
    from part6 import catalog
    assert catalog.visitor_entries(CONFORMANCE) == []
    assert all(conf(e.name).get("visitor") in (None, False) for e in CONFORMANCE.iterdir())


def test_the_import_entries_come_through_the_importer_with_the_dropped_names():
    skeleton = conf("conf-import-skeleton")["provenance"]
    assert skeleton["keyframes"]["original_name"] == "keyframes.json"
    assert skeleton["skeleton"]["source"] == "fixtures/conformance/formats"
    assert conf("conf-import-part4")["provenance"]["animation"]["part"] == 4


def test_rerunning_the_conformance_generator_changes_nothing(tmp_path):
    entries_generator().build(tmp_path / "again")
    assert tree(tmp_path / "again") == tree(CONFORMANCE)


def test_conformance_generator_is_independent_of_the_clock(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from part6 import catalog
    monkeypatch.setattr(catalog, "utc_now", lambda: datetime(1999, 1, 1, tzinfo=timezone.utc))
    entries_generator().build(tmp_path / "other-day")
    assert tree(tmp_path / "other-day") == tree(CONFORMANCE)


def test_conformance_generator_replaces_old_folders_and_keeps_other_files(tmp_path):
    out = tmp_path / "out"
    (out / "conf-mock-a").mkdir(parents=True)
    (out / "conf-mock-a" / "stale.txt").write_text("old")
    (out / "notes.txt").write_text("keep")
    ids = entries_generator().build(out)
    assert len(ids) == 8 and not (out / "conf-mock-a" / "stale.txt").exists()
    assert (out / "notes.txt").read_text() == "keep"
    assert not [p for p in out.iterdir() if p.name.startswith(".")]


def test_conformance_generator_says_plainly_when_a_golden_is_missing(tmp_path, monkeypatch):
    module = entries_generator()
    monkeypatch.setattr(module, "FORMATS", tmp_path / "no-goldens")
    with pytest.raises(SystemExit, match="make_goldens.py"):
        module.build(tmp_path / "out")


def test_the_fake_processor_runs_without_pauses_and_the_environment_is_put_back(
        tmp_path, monkeypatch):
    import os
    import time
    monkeypatch.delenv("SIMON6_FAKE_STAGE_S", raising=False)
    began = time.monotonic()
    entries_generator().build(tmp_path / "quick")
    assert time.monotonic() - began < 5 and "SIMON6_FAKE_STAGE_S" not in os.environ
    monkeypatch.setenv("SIMON6_FAKE_STAGE_S", "0.25")
    entries_generator().build(tmp_path / "again")
    assert os.environ["SIMON6_FAKE_STAGE_S"] == "0.25"
