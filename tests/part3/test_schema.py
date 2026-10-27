"""Input and output validators (AC-001, AC-002; contract-pose3d-input.md, contract-skeleton-output.md)."""

import copy
import json
import subprocess
import sys

import pytest

from clipkit import real_skeleton
from conftest import ROOT
from part3.joints import JOINTS
from part3.schema import ContractError, validate_pose3d, validate_skeleton


def base(real_doc, frames=6):
    return {"frames": copy.deepcopy(real_doc["frames"][:frames])}


def joint(d, f=3, name="nose"):
    return d["frames"][f]["people"][0]["joints"][name]


def drop_joint(d):
    del d["frames"][3]["people"][0]["joints"]["left_knee"]


def extra_joint(d):
    d["frames"][3]["people"][0]["joints"]["tail"] = {"x": 0, "y": 0, "z": 0, "conf": 1}


def dup_id(d):
    d["frames"][2]["people"].append(copy.deepcopy(d["frames"][2]["people"][0]))


# (name, mutation, expected path, expected message fragment)
INVALID = [
    ("doc not an object", lambda d: None, "pose3d", "expected an object"),
    ("frames not a list", lambda d: d.update(frames={"a": 1}), "pose3d.frames", "expected a list"),
    ("frames missing", lambda d: d.pop("frames"), "pose3d.frames", "expected a list"),
    ("frame entry not an object", lambda d: d["frames"].__setitem__(1, 5), "pose3d.frames[1]",
     "expected an object"),
    ("frame not an integer", lambda d: d["frames"][2].update(frame="2"), "pose3d.frames[2].frame",
     "expected an integer"),
    ("frame is a bool", lambda d: d["frames"][2].update(frame=True), "pose3d.frames[2].frame",
     "expected an integer"),
    ("frame repeats", lambda d: d["frames"][3].update(frame=d["frames"][2]["frame"]),
     "pose3d.frames[3].frame", "frame indices must be strictly increasing"),
    ("frame goes backwards", lambda d: d["frames"][4].update(frame=-1), "pose3d.frames[4].frame",
     "frame indices must be strictly increasing"),
    ("t_ms NaN", lambda d: d["frames"][4].update(t_ms=float("nan")), "pose3d.frames[4].t_ms",
     "expected a finite number"),
    ("t_ms infinite", lambda d: d["frames"][4].update(t_ms=float("inf")), "pose3d.frames[4].t_ms",
     "expected a finite number"),
    ("t_ms a string", lambda d: d["frames"][4].update(t_ms="66.6"), "pose3d.frames[4].t_ms",
     "expected a finite number"),
    ("t_ms missing", lambda d: d["frames"][4].pop("t_ms"), "pose3d.frames[4].t_ms",
     "expected a finite number"),
    ("people not a list", lambda d: d["frames"][1].update(people={}), "pose3d.frames[1].people",
     "expected a list"),
    ("person not an object", lambda d: d["frames"][1]["people"].__setitem__(0, []),
     "pose3d.frames[1].people[0]", "expected an object"),
    ("id is a bool", lambda d: d["frames"][2]["people"][0].update(id=True),
     "pose3d.frames[2].people[0].id", "expected an integer or a string"),
    ("id is a float", lambda d: d["frames"][2]["people"][0].update(id=1.5),
     "pose3d.frames[2].people[0].id", "expected an integer or a string"),
    ("id missing", lambda d: d["frames"][2]["people"][0].pop("id"),
     "pose3d.frames[2].people[0].id", "expected an integer or a string"),
    ("duplicate id in a frame", dup_id, "pose3d.frames[2].people[1].id", "duplicate id"),
    ("a joint is missing", drop_joint, "pose3d.frames[3].people[0].joints",
     "expected the 17 canonical joints (missing left_knee)"),
    ("an extra joint", extra_joint, "pose3d.frames[3].people[0].joints",
     "expected the 17 canonical joints (unexpected tail)"),
    ("joints not an object", lambda d: d["frames"][3]["people"][0].update(joints=[]),
     "pose3d.frames[3].people[0].joints", "expected the 17 canonical joints"),
    ("coordinate NaN", lambda d: joint(d, 3, "left_knee").update(y=float("nan")),
     "pose3d.frames[3].people[0].joints.left_knee.y", "expected a finite number"),
    ("coordinate infinite", lambda d: joint(d).update(x=float("-inf")),
     "pose3d.frames[3].people[0].joints.nose.x", "expected a finite number"),
    ("coordinate a string", lambda d: joint(d).update(z="0.3"),
     "pose3d.frames[3].people[0].joints.nose.z", "expected a finite number"),
    ("coordinate missing", lambda d: joint(d).pop("z"),
     "pose3d.frames[3].people[0].joints.nose.z", "expected a finite number"),
    ("coordinate beyond float range", lambda d: joint(d).update(x=10 ** 400),
     "pose3d.frames[3].people[0].joints.nose.x", "expected a finite number"),
    ("conf above 1", lambda d: joint(d).update(conf=1.2),
     "pose3d.frames[3].people[0].joints.nose.conf", "1.2 not in [0, 1]"),
    ("conf below 0", lambda d: joint(d).update(conf=-0.1),
     "pose3d.frames[3].people[0].joints.nose.conf", "-0.1 not in [0, 1]"),
    ("conf a string", lambda d: joint(d).update(conf="1"),
     "pose3d.frames[3].people[0].joints.nose.conf", "expected a number in [0, 1]"),
    ("conf NaN", lambda d: joint(d).update(conf=float("nan")),
     "pose3d.frames[3].people[0].joints.nose.conf", "not in [0, 1]"),
    ("mirrored not a boolean", lambda d: d.update(mirrored=1), "pose3d.mirrored",
     "expected true or false"),
    ("mirrored a string", lambda d: d.update(mirrored="yes"), "pose3d.mirrored",
     "expected true or false"),
]


@pytest.mark.parametrize("name,mutate,path,fragment", INVALID, ids=[c[0] for c in INVALID])
def test_input_contract_rows(real_doc, name, mutate, path, fragment):
    doc = base(real_doc)
    if name == "doc not an object":
        doc = [1, 2]
    else:
        mutate(doc)
    with pytest.raises(ContractError) as caught:
        validate_pose3d(doc)
    assert caught.value.path == path
    assert fragment in caught.value.msg
    assert str(caught.value) == f"{path}: {caught.value.msg}"


def test_real_fixture_is_valid(real_doc):
    validate_pose3d(real_doc)


def test_valid_variants_pass(real_doc):
    doc = base(real_doc)
    doc["frames"][2]["people"] = []  # an empty people list is allowed
    doc["frames"][3]["people"][0]["id"] = "athlete-é"  # string ids are allowed
    doc["mirrored"] = False
    validate_pose3d(doc)
    doc["mirrored"] = True
    doc["frames"][0]["t_ms"] = 0  # an int is a number
    validate_pose3d(doc)
    validate_pose3d({"frames": []})


def test_unknown_extra_keys_are_ignored(real_doc):
    doc = base(real_doc)
    doc["camera_facing"] = "front"
    doc["schema"] = "anything"
    doc["frames"][1]["note"] = [1, 2]
    doc["frames"][1]["people"][0]["flips_repaired"] = ["legs"]
    joint(doc, 1)["extra"] = "x"
    validate_pose3d(doc)


def test_contract_error_attributes():
    error = ContractError("pose3d.frames[3].t_ms", "expected a finite number")
    assert (error.path, error.msg) == ("pose3d.frames[3].t_ms", "expected a finite number")
    assert str(error) == "pose3d.frames[3].t_ms: expected a finite number"
    assert isinstance(error, Exception)


def test_cli_rejects_invalid_input_names_path_and_writes_nothing(real_doc, tmp_path):
    doc = base(real_doc, 8)
    joint(doc, 3).update(conf=1.2)
    source, target = tmp_path / "bad.json", tmp_path / "skeleton.json"
    source.write_text(json.dumps(doc))
    run = subprocess.run([sys.executable, "-m", "part3", "run", "--in", str(source), "--out", str(target)],
                         cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 2
    assert "pose3d.frames[3].people[0].joints.nose.conf" in run.stderr
    assert "1.2 not in [0, 1]" in run.stderr
    assert not target.exists()


# --- skeleton.json ------------------------------------------------------------------------------

def skeleton_mutations():
    def first_person(s):
        return s["frames"][10]["people"][0]

    return [
        ("schema string", lambda s: s.update(schema="simon.skeleton/2"), "skeleton.schema"),
        ("units", lambda s: s["units"].update(length="cm"), "skeleton.units"),
        ("frame block", lambda s: s["frame"].update(y="camera_up"), "skeleton.frame.y"),
        ("up_source", lambda s: s["frame"].update(up_source="camera"), "skeleton.frame.up_source"),
        ("joint order", lambda s: s["joints"].reverse(), "skeleton.joints"),
        ("bones order", lambda s: s["bones"].reverse(), "skeleton.bones"),
        ("bones count", lambda s: s["bones"].pop(), "skeleton.bones"),
        ("standard stature", lambda s: s["standard"].update(stature_m=1.8), "skeleton.standard.stature_m"),
        ("standard sources", lambda s: s["standard"].update(sources=[]), "skeleton.standard.sources"),
        ("standard lengths", lambda s: s["bone_lengths_m"].update(left_thigh=0.5), "skeleton.bone_lengths_m"),
        ("person rule", lambda s: s["person"].update(rule="first"), "skeleton.person.rule"),
        ("person few_frames", lambda s: s["person"].update(few_frames=True), "skeleton.person.few_frames"),
        ("person frames_present", lambda s: s["person"].update(frames_present=106),
         "skeleton.person.candidates"),
        ("flips total", lambda s: s["person"]["flips_repaired_total"].update(legs=1),
         "skeleton.person.flips_repaired_total"),
        ("measured lengths", lambda s: s["person"]["measured_bone_lengths_m"].pop("spine"),
         "skeleton.person.measured_bone_lengths_m"),
        ("mirror setting", lambda s: s["mirror"].update(setting="maybe"), "skeleton.mirror.setting"),
        ("mirror applied", lambda s: s["mirror"].update(applied="no"), "skeleton.mirror.applied"),
        ("mirror reason", lambda s: s["mirror"].update(reason="because"), "skeleton.mirror.reason"),
        ("sha256", lambda s: s["input"].update(sha256="abc"), "skeleton.input.sha256"),
        ("two people in a frame",
         lambda s: s["frames"][10]["people"].append({**copy.deepcopy(first_person(s)), "id": 9}),
         "skeleton.frames[10].people"),
        ("person id differs", lambda s: first_person(s).update(id=5), "skeleton.frames[10].people[0].id"),
        ("flips order", lambda s: first_person(s).update(flips_repaired=["legs", "body"]),
         "skeleton.frames[10].people[0].flips_repaired"),
        ("flips unknown group", lambda s: first_person(s).update(flips_repaired=["torso"]),
         "skeleton.frames[10].people[0].flips_repaired"),
        ("flips missing", lambda s: first_person(s).pop("flips_repaired"),
         "skeleton.frames[10].people[0].flips_repaired"),
        ("five decimals", lambda s: first_person(s)["joints"]["nose"].update(x=0.12345),
         "skeleton.frames[10].people[0].joints.nose.x"),
        ("negative zero", lambda s: first_person(s)["joints"]["nose"].update(y=-0.0),
         "skeleton.frames[10].people[0].joints.nose.y"),
        ("not a valid pose3d", lambda s: first_person(s)["joints"]["nose"].update(conf=1.5),
         "skeleton.frames[10].people[0].joints.nose.conf"),
        ("frame numbers", lambda s: s["frames"][5].update(frame=s["frames"][4]["frame"]),
         "skeleton.frames[5].frame"),
    ]


def test_skeleton_of_real_fixture_is_valid():
    validate_skeleton(real_skeleton())


@pytest.mark.parametrize("case", skeleton_mutations(), ids=lambda c: c[0])
def test_skeleton_rule_rejected(case):
    _, mutate, path = case
    skeleton = real_skeleton()
    mutate(skeleton)
    with pytest.raises(ContractError) as caught:
        validate_skeleton(skeleton)
    assert caught.value.path == path


def test_skeleton_is_also_a_valid_pose3d():
    validate_pose3d(real_skeleton())


def test_skeleton_not_an_object():
    with pytest.raises(ContractError) as caught:
        validate_skeleton([])
    assert caught.value.path == "skeleton"


def test_skeleton_may_hold_frames_without_the_person():
    skeleton = real_skeleton()
    skeleton["frames"][4]["people"] = []
    skeleton["person"]["frames_present"] -= 1
    skeleton["person"]["frames_dropped"] += 1
    validate_skeleton(skeleton)


def run_schema(path):
    return subprocess.run([sys.executable, "-m", "part3.schema", str(path)], cwd=ROOT,
                          capture_output=True, text=True)


def test_schema_module_exit_codes(tmp_path):
    good, bad, junk = tmp_path / "good.json", tmp_path / "bad.json", tmp_path / "junk.json"
    good.write_text(json.dumps(real_skeleton()))
    broken = real_skeleton()
    broken["schema"] = "nope"
    bad.write_text(json.dumps(broken))
    junk.write_text("{not json")
    assert run_schema(good).returncode == 0
    refused = run_schema(bad)
    assert refused.returncode == 2 and "skeleton.schema" in refused.stderr
    assert run_schema(junk).returncode == 2
    assert run_schema(tmp_path / "missing.json").returncode == 2
    no_args = subprocess.run([sys.executable, "-m", "part3.schema"], cwd=ROOT, capture_output=True, text=True)
    assert no_args.returncode == 2


def test_joint_names_in_input_contract_are_the_canonical_17():
    assert len(JOINTS) == 17 and JOINTS[0] == "nose" and JOINTS[-1] == "right_ankle"
