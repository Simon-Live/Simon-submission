"""Part 5's input contract (CONTRACT.md): every file Parts 3 and 4 publish for Part 5 loads through
part5.io.load_clip and validates against the schema it was copied with (contracts/)."""
import hashlib
import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5.io import JOINTS, InputError, load_clip

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
P3 = ROOT / "fixtures/input/contract/part3"
P4 = ROOT / "fixtures/input/contract/part4"
LOCK = json.loads((CONTRACTS / "sources.lock.json").read_text())
P3_TAKES = sorted(P3.glob("followers/*/skeleton.json"))

# CONTRACT.md "Fault labels": Part 3 kit type -> closest Part 5 type (Part 3 CONTRACT.md, 65a5aad).
KIT_TO_PART5 = {"feet_wide": "foot_out", "elbows_out": "arms_wider", "shallow_squat": "knees_shallow",
                "knee_caving": None}


def schema(name):
    return jsonschema.Draft202012Validator(json.loads((CONTRACTS / name).read_text()))


def assert_valid(validator, path):
    errors = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}"
              for e in validator.iter_errors(json.loads(Path(path).read_text()))]
    assert not errors, f"{path}: {errors[:3]}"


@pytest.mark.parametrize("dst", sorted(LOCK["files"]))
def test_copies_match_the_lock(dst):
    """Each copy is byte-for-byte what the lock recorded from upstream; edit upstream, not here."""
    assert hashlib.sha256((ROOT / dst).read_bytes()).hexdigest() == LOCK["files"][dst]["sha256"]


@pytest.mark.parametrize("name", ["part3/animation-part5.schema.json", "part3/skeleton.schema.json",
                                  "part3/skeleton-part4.schema.json", "part3/follower-labels.schema.json",
                                  "part4/animation.schema.json"])
def test_schemas_are_valid_draft_2020_12(name):
    jsonschema.Draft202012Validator.check_schema(json.loads((CONTRACTS / name).read_text()))


def test_part3_kit_has_three_angles_with_correct_and_fault_takes():
    labels = json.loads((P3 / "followers/labels.json").read_text())
    angles = {t["angle"] for t in labels["takes"]}
    assert angles == {"front", "45", "side"}
    for a in angles:
        takes = [t for t in labels["takes"] if t["angle"] == a]
        assert any(t["correct"] for t in takes) and any(not t["correct"] for t in takes)
    assert len(P3_TAKES) == len(labels["takes"])


@pytest.mark.parametrize("path", P3_TAKES, ids=lambda p: p.parent.name)
def test_part3_follower_take_loads_and_matches_schema(path):
    assert_valid(schema("part3/animation-part5.schema.json"), path)
    doc = json.loads(path.read_text())
    clip = load_clip(path)
    assert clip.format == "simon.animation.v1"
    assert clip.positions.shape == (doc["frame_count"], len(JOINTS), 3)
    assert clip.fps == doc["fps"]
    assert np.allclose(clip.t, [f["t"] for f in doc["frames"]])
    assert not clip.interpolated.any()
    assert clip.mask.all()  # Part 3 writes conf >= 0.3 on every joint, Part 5's cutoff keeps 0.3


def test_part3_labels_validate_and_map_onto_part5_types():
    assert_valid(schema("part3/follower-labels.schema.json"), P3 / "followers/labels.json")
    labels = json.loads((P3 / "followers/labels.json").read_text())
    part5 = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    part5_types = {f["type"] for t in part5["takes"] for f in t["faults"]}
    for take in labels["takes"]:
        assert (P3 / take["follower"]).exists()
        for fault in take["faults"]:
            assert fault["type"] in KIT_TO_PART5, f"unmapped Part 3 fault type {fault['type']}"
            mapped = KIT_TO_PART5[fault["type"]]
            assert mapped is None or mapped in part5_types


def test_part3_part4_view_loads_as_expected_skeleton():
    path = P3 / "view-part4/skeleton.json"
    assert_valid(schema("part3/skeleton-part4.schema.json"), path)
    doc = json.loads(path.read_text())
    clip = load_clip(path)
    assert clip.format == "simon.skeleton.v1"
    assert clip.n_frames == len(doc["keyframes"])
    assert clip.fps == 30  # the view carries a top-level fps (Part 3 65a5aad); each key still has t


def test_part3_native_skeleton_is_rejected_with_the_fix_named_by_part3():
    path = P3 / "native/skeleton.json"
    assert_valid(schema("part3/skeleton.schema.json"), path)
    with pytest.raises(InputError, match="format must be one of"):
        load_clip(path)


def test_part4_animation_loads_and_matches_both_schemas():
    path = P4 / "exercise/animation.json"
    assert_valid(schema("part4/animation.schema.json"), path)
    assert_valid(schema("part3/animation-part5.schema.json"), path)
    doc = json.loads(path.read_text())
    clip = load_clip(path)
    assert clip.fps == 30
    assert clip.n_frames == doc["frame_count"]
    assert np.allclose(clip.t, np.arange(clip.n_frames) / 30, atol=1e-6)
    assert clip.interpolated.tolist() == [f["interpolated"] for f in doc["frames"]]
    assert clip.mask.all()


def test_part5_own_input_fixtures_are_in_the_published_shape():
    v = schema("part3/animation-part5.schema.json")
    paths = sorted((ROOT / "fixtures/input/expected").glob("*/animation.json"))
    paths += sorted((ROOT / "fixtures/input/followers").glob("*/*/skeleton.json"))
    assert len(paths) > 2
    for p in paths:
        assert_valid(v, p)
