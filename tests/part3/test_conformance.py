"""The conformance kit (AC-K01 to AC-K03): inputs, cases, the checks and their failures.

The end-to-end rebuild with the real CLI needs the integrated tree (views, profiles, contracts, the
validator); it skips until `contracts/` and the committed goldens exist. The checks themselves run on a
stand-in runner (native output for every option) so tampering is tested on any tree.
"""

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT
from part3 import cli, conformance, followers, io
from part3.angles import joints_array
from part3.conformance import Closed

KIT = ROOT / "fixtures" / "conformance"
NON_CANONICAL = ("pose3d.arrays.json", "pose3d.joint-list.json", "pose3d.extra-joints.json", "pose3d.no-t_ms.json",
                 "pose3d.flat.json")
CONTRACT_FILES = ("pose3d", "keyframes-part1", "keyframes-part4", "body-profile", "skeleton", "skeleton-part4",
                  "animation-part5", "people-index", "follower-labels")


def load(rel):
    return json.loads((KIT / rel).read_text())


# ---- inputs -----------------------------------------------------------------------------------------

def test_committed_inputs_cases_and_follower_inputs_are_what_the_code_builds():
    built = {**conformance.input_files(), **conformance.follower_input_files()}
    for rel, text in built.items():
        assert (KIT / rel).read_text() == text, rel


def test_every_input_file_is_valid_json_and_the_squat_is_referenced_not_copied():
    names = sorted(p.name for p in (KIT / "inputs").iterdir())
    assert names == ["keyframes.part1.json", "keyframes.part4.json", "pose3d.arrays.json", "pose3d.extra-joints.json",
                     "pose3d.flat.json", "pose3d.joint-list.json", "pose3d.no-t_ms.json", "pose3d.two-people.json",
                     "profile.example.json"]
    assert all(c["input"] == conformance.SQUAT or c["input"].startswith(conformance.INPUTS)
               for c in load("cases.json"))


def test_joints_as_arrays_copy_has_x_y_z_conf_lists():
    joints = load("inputs/pose3d.arrays.json")["frames"][0]["people"][0]["joints"]
    assert set(joints) == set(conformance.JOINTS) and all(len(v) == 4 for v in joints.values())


def test_joint_list_copy_is_17_arrays_in_canonical_order():
    original = load("inputs/pose3d.arrays.json")["frames"][3]["people"][0]["joints"]
    listed = load("inputs/pose3d.joint-list.json")["frames"][3]["people"][0]["joints"]
    assert isinstance(listed, list) and listed == [original[n] for n in conformance.JOINTS]


def test_extra_joints_copy_adds_names_beyond_the_canonical_17():
    joints = load("inputs/pose3d.extra-joints.json")["frames"][0]["people"][0]["joints"]
    assert set(joints) - set(conformance.JOINTS) == {"pelvis", "neck"}


def test_copy_without_t_ms_has_a_top_level_fps():
    doc = load("inputs/pose3d.no-t_ms.json")
    assert doc["fps"] == 15 and all("t_ms" not in f for f in doc["frames"])


def test_flat_copy_has_joints_on_the_frame_and_no_frame_number():
    frame = load("inputs/pose3d.flat.json")["frames"][0]
    assert set(frame) == {"t_ms", "joints"}


def test_two_person_copy_has_a_string_id_in_fewer_frames_and_shifted_scaled_joints():
    doc = load("inputs/pose3d.two-people.json")
    counts = {}
    for frame in doc["frames"]:
        for person in frame["people"]:
            counts[person["id"]] = counts.get(person["id"], 0) + 1
    assert counts == {0: 107, "guest": 87}
    both = next(f for f in doc["frames"] if len(f["people"]) == 2)
    first, second = (p["joints"]["left_hip"] for p in both["people"])
    assert second["x"] == pytest.approx(first["x"] * 0.94 + 0.30, abs=1e-4) and second["conf"] == first["conf"]


def test_part1_keyframes_are_on_the_60_fps_video_clock_with_two_repetitions():
    doc = load("inputs/keyframes.part1.json")
    assert doc["fps"] == 60.0 and doc["people"][0]["id"] == 0
    reps = doc["people"][0]["repetitions"]
    assert [r["rep"] for r in reps] == [1, 2] and all(r["movement"] == "squat" for r in reps)
    keys = [k for r in reps for k in r["keyframes"]]
    assert [k["name"] for k in keys] == ["start", "bottom", "top"] * 2
    assert [k["t_ms"] for k in keys] == sorted(k["t_ms"] for k in keys)
    assert all(k["frame"] == round(k["t_ms"] * 60 / 1000) for k in keys)


def test_squat_keys_find_the_bottoms_from_hip_height():
    reps = conformance.squat_keys(conformance._squat_doc())
    assert len(reps) == 2
    for _, keys in reps:
        (_, start), (_, bottom), (_, top) = keys
        assert start < bottom < top
    assert [pos for _, keys in reps for _, pos in keys] == sorted(pos for _, keys in reps for _, pos in keys)
    assert reps[0][1][1][1] == 35  # the first deepest frame of the real squat


def test_part4_keyframes_are_simon_keyframes_v1_at_30_fps_inside_the_clip():
    doc = load("inputs/keyframes.part4.json")
    assert doc["format"] == "simon.keyframes.v1" and doc["fps"] == 30
    assert doc["frame_count"] == 213 and doc["duration_s"] == pytest.approx(212 / 30, abs=1e-6)
    indices = [k["index"] for k in doc["keyframes"]]
    assert indices == sorted(set(indices)) and 0 <= indices[0] and indices[-1] < doc["frame_count"]
    assert all(abs(k["t"] - k["index"] / 30) < 1e-6 for k in doc["keyframes"])


def test_example_profile_is_a_1_62_m_body_with_equal_halves_and_a_source():
    doc = load("inputs/profile.example.json")
    assert doc["schema"] == "simon.body_profile/1" and doc["stature_m"] == 1.62 and doc["source"]
    lengths = doc["bone_lengths_m"]
    assert len(lengths) == 18 and all(0.005 <= v <= 1.5 for v in lengths.values())
    assert lengths["left_pelvis"] == lengths["right_pelvis"] and lengths["left_clavicle"] == lengths["right_clavicle"]
    assert lengths["left_thigh"] == lengths["right_thigh"] and lengths["left_thigh"] < 0.4165


# ---- cases ------------------------------------------------------------------------------------------

def test_cases_cover_every_profile_view_people_option_and_adapter():
    cases = {c["id"]: c for c in load("cases.json")}
    assert len(cases) == len(load("cases.json"))
    args = [" ".join(c["args"]) for c in cases.values()]
    for needle in ("--body simon-standard", "--body part4-rig", "--body measured", "--body file:", "--stature 1.85",
                   "--view native", "--view part4 --body part4-rig --keyframes", "--view part5", "--fps 30",
                   "--person guest", "--all-people", "--input-fps 15", "keyframes.part4.json", "keyframes.part1.json",
                   "every:10"):
        assert any(needle in a for a in args), needle
    inputs = {c["input"].rsplit("/", 1)[-1] for c in cases.values()}
    assert {"pose3d.arrays.json", "pose3d.joint-list.json", "pose3d.extra-joints.json", "pose3d.no-t_ms.json",
            "pose3d.flat.json", "pose3d.two-people.json", "pose3d.json"} == inputs
    assert conformance.REFERENCE_CASE in cases


def test_every_case_names_its_expected_outputs():
    for case in load("cases.json"):
        assert set(case) == {"id", "input", "args", "outputs"} and (ROOT / case["input"]).is_file()
        assert ("keyframes.json" in case["outputs"]) == ("--keyframes-out" in case["args"])
        if "--all-people" in case["args"]:
            assert case["outputs"] == ["people.json", "person-0/skeleton.json", "person-guest/skeleton.json"]
        else:
            assert case["outputs"][0] == "skeleton.json"


def test_the_case_arguments_point_keyframes_out_into_the_case_folder(tmp_path):
    case = next(c for c in load("cases.json") if c["id"] == "view-part4-part1-keyframes")
    args = conformance._case_args(case, tmp_path)
    assert args[args.index("--keyframes-out") + 1] == str(tmp_path / "golden" / case["id"] / "keyframes.json")
    assert args[args.index("--out") + 1] == str(tmp_path / "golden" / case["id"] / "skeleton.json")
    many = conformance._case_args(next(c for c in load("cases.json") if c["id"] == "all-people"), tmp_path)
    assert many[many.index("--out") + 1] == str(tmp_path / "golden" / "all-people")


# ---- the file kinds ---------------------------------------------------------------------------------

@pytest.mark.parametrize("doc,name", [
    ({"schema": "simon.skeleton/1"}, "skeleton.schema.json"),
    ({"format": "simon.skeleton.v1"}, "skeleton-part4.schema.json"),
    ({"format": "simon.animation.v1"}, "animation-part5.schema.json"),
    ({"format": "simon.keyframes.v1"}, "keyframes-part4.schema.json"),
    ({"schema": "simon.part3.people/1"}, "people-index.schema.json"),
    ({"schema": "simon.body_profile/1"}, "body-profile.schema.json"),
    ({"format": "simon.part3.follower_labels/1"}, "follower-labels.schema.json"),
    ({"people": [{"id": 0, "repetitions": []}]}, "keyframes-part1.schema.json"),
    ({"frames": []}, "pose3d.schema.json"),
    ({"other": 1}, None), ([], None), ({"schema": "unknown/9"}, None),
    ({"format": ["unhashable"], "schema": "simon.skeleton/1"}, "skeleton.schema.json"),
    ({"format": "unknown/9", "schema": "simon.skeleton/1"}, "skeleton.schema.json"),
])
def test_schema_name_is_chosen_by_the_file_kind(doc, name):
    assert conformance.schema_name(doc) == name


def test_b4_a_document_with_both_format_and_schema_is_checked_against_the_part4_schema():
    """A part4 view carries `format: simon.skeleton.v1` and the native `schema: simon.skeleton/1`."""
    both = {"format": "simon.skeleton.v1", "schema": "simon.skeleton/1"}
    assert conformance.schema_name(both) == "skeleton-part4.schema.json"
    assert conformance.schema_name({**both, "format": "simon.animation.v1"}) == "animation-part5.schema.json"
    committed = load("golden/view-part4-every-10/skeleton.json")
    assert committed["schema"] == "simon.skeleton/1" and committed["format"] == "simon.skeleton.v1"
    assert conformance.schema_name(committed) == "skeleton-part4.schema.json"


def test_b4_a_corrupted_part4_golden_fails_the_part4_schema_it_used_to_slip_past_the_native_one(tmp_path, monkeypatch):
    jsonschema_lite = pytest.importorskip("part3.jsonschema_lite")
    doc = load("golden/view-part4-every-10/skeleton.json")
    doc["rest_offsets_m"]["neck"]["parent"] = "chest"
    doc["keyframes"][0]["local_rotations"]["pelvis"] = "not a quaternion"
    path = tmp_path / "skeleton.json"
    path.write_text(io.dumps(doc))
    native_schema = json.loads((ROOT / "contracts" / "skeleton.schema.json").read_text())
    assert jsonschema_lite.validate(doc, native_schema) == []  # what the old order of checks compared it with
    monkeypatch.setattr(conformance, "files_to_validate", lambda kit: [path])
    count, tried, failures = conformance.validate_files(tmp_path, ROOT / "contracts", jsonschema_lite.validate)
    assert (count, tried) == (0, 1)
    assert failures and all("does not match skeleton-part4.schema.json" in f for f in failures)


def test_b4_the_three_committed_part4_goldens_pass_the_part4_schema(monkeypatch):
    jsonschema_lite = pytest.importorskip("part3.jsonschema_lite")
    paths = [KIT / "golden" / case / "skeleton.json"
             for case in ("view-part4-every-10", "view-part4-part1-keyframes", "view-part4-part4-keyframes")]
    monkeypatch.setattr(conformance, "files_to_validate", lambda kit: paths)
    assert conformance.validate_files(KIT, ROOT / "contracts", jsonschema_lite.validate) == (3, 3, [])


# ---- fail closed ------------------------------------------------------------------------------------

def test_check_fails_closed_without_the_contracts_folder(tmp_path):
    with pytest.raises(Closed, match="contracts folder is missing"):
        conformance.check(contracts=tmp_path / "nope")


def test_check_fails_closed_without_the_validator(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "part3.jsonschema_lite", None)
    with pytest.raises(Closed, match="part3.jsonschema_lite is missing"):
        conformance.check(contracts=tmp_path)


def test_main_exits_1_with_a_plain_reason_when_it_cannot_run(monkeypatch, capsys):
    def closed(**_):
        raise Closed("the contracts folder is missing")

    monkeypatch.setattr(conformance, "check", closed)
    assert conformance.main(["check"]) == 1
    captured = capsys.readouterr()
    assert "cannot run: the contracts folder is missing" in captured.err
    assert json.loads(captured.out)["pass"] is False


def test_main_rejects_an_unknown_command(capsys):
    assert conformance.main(["build-everything"]) == 2
    assert "usage" in capsys.readouterr().err


# ---- the checks on a stand-in runner ----------------------------------------------------------------

def stand_in(args):
    """The CLI in this process, writing native output for every option but `--view part5`.

    The part5 view is kept because the fault check reads the follower takes' part5 files. An input in a
    tolerated, non-canonical shape is replaced by the real squat: it needs the input adapters.
    """
    args = list(args)
    source, out = args[args.index("--in") + 1], pathlib.Path(args[args.index("--out") + 1])
    if pathlib.Path(source).name in NON_CANONICAL:
        source = str(ROOT / conformance.SQUAT)
    many = "--all-people" in args
    target = out / "skeleton.json" if many else out
    target.parent.mkdir(parents=True, exist_ok=True)
    view = ["--view", "part5"] if "part5" in args else []
    code = cli.main(["run", "--in", source, "--out", str(target), *view])
    if many:
        io.write_text(out / "people.json", io.dumps({"schema": "simon.part3.people/1", "people": []}))
        for rel in conformance.ALL_PEOPLE_OUTPUTS[1:]:
            io.write_text(out / rel, target.read_text(), mkdir=True)
        target.unlink()
    if "--keyframes-out" in args:
        io.write_text(args[args.index("--keyframes-out") + 1], io.dumps({"format": "simon.keyframes.v1"}))
    return code, ""


def accept_all(instance, schema):
    return []


@pytest.fixture(scope="module")
def stand_in_kit(tmp_path_factory):
    root = tmp_path_factory.mktemp("stand-in")
    kit, contracts = root / "kit", root / "contracts"
    contracts.mkdir()
    for name in CONTRACT_FILES:
        (contracts / f"{name}.schema.json").write_text("{}")
    assert conformance.build(kit, runner=stand_in) == []
    return kit, contracts


def run_check(kit, contracts):
    return conformance.check(kit, contracts, runner=stand_in, validator=accept_all)


def copy_kit(stand_in_kit, tmp_path):
    kit, contracts = stand_in_kit
    shutil.copytree(kit, tmp_path / "kit")
    return tmp_path / "kit", contracts


def test_ac_k01_a_clean_kit_passes_and_the_metrics_count_cases_files_and_faults(stand_in_kit):
    metrics, failures = run_check(*stand_in_kit)
    assert failures == [] and metrics["pass"] is True
    assert metrics["cases"] == 21 and metrics["takes"] == 15
    assert metrics["faults_visible"] == metrics["faults_total"] == 12
    assert metrics["correct_takes_clean"] == metrics["correct_takes_total"] == 3
    assert metrics["files_rebuilt_identical"] == metrics["files_rebuilt_total"] == 83
    assert metrics["files_validated"] == metrics["files_validated_total"] > 50 and metrics["failures"] == 0


def test_the_built_kit_has_the_documented_layout(stand_in_kit):
    kit, _ = stand_in_kit
    assert (kit / "golden" / "all-people" / "people.json").is_file()
    assert (kit / "golden" / "view-part4-part1-keyframes" / "keyframes.json").is_file()
    for td in followers.take_defs():
        for name in ("input/pose3d.json", "skeleton.json", "skeleton.native.json"):
            assert (kit / "followers" / td.take_id / name).is_file(), (td.take_id, name)
    assert load_labels(kit)["format"] == "simon.part3.follower_labels/1"


def load_labels(kit):
    return json.loads((kit / "followers" / "labels.json").read_text())


def test_built_labels_carry_a_measured_size_within_half_the_applied_size(stand_in_kit):
    kit, _ = stand_in_kit
    for take in load_labels(kit)["takes"]:
        for fault in take["faults"]:
            applied = fault.get("magnitude_deg", fault.get("magnitude_m"))
            assert 0.5 * applied <= fault["measured_in_output"] <= 1.5 * applied, take["take_id"]


def test_ac_k02_one_changed_byte_in_a_golden_file_fails_and_names_it(stand_in_kit, tmp_path):
    kit, contracts = copy_kit(stand_in_kit, tmp_path)
    golden = kit / "golden" / "profile-measured" / "skeleton.json"
    data = bytearray(golden.read_bytes())
    data[200] = ord("7") if data[200] != ord("7") else ord("8")
    golden.write_bytes(bytes(data))
    metrics, failures = run_check(kit, contracts)
    assert metrics["pass"] is False
    assert any("golden/profile-measured/skeleton.json" in f and "differs from a rebuild" in f for f in failures)


def test_ac_k02_one_changed_coordinate_in_a_follower_take_fails_and_names_it(stand_in_kit, tmp_path):
    kit, contracts = copy_kit(stand_in_kit, tmp_path)
    take = kit / "followers" / "squat_45_elbows_out" / "input" / "pose3d.json"
    doc = json.loads(take.read_text())
    doc["frames"][50]["people"][0]["joints"]["left_wrist"]["x"] += 0.001
    take.write_text(io.dumps(doc))
    metrics, failures = run_check(kit, contracts)
    assert metrics["pass"] is False
    assert any("squat_45_elbows_out/input/pose3d.json" in f and "differs" in f for f in failures)
    assert any("squat_45_elbows_out/skeleton.native.json" in f for f in failures)  # the output no longer follows


def test_a_missing_golden_and_a_stray_file_fail_and_name_the_file(stand_in_kit, tmp_path):
    kit, contracts = copy_kit(stand_in_kit, tmp_path)
    (kit / "golden" / "fps-30" / "skeleton.json").unlink()
    (kit / "golden" / "stale-case").mkdir()
    (kit / "golden" / "stale-case" / "skeleton.json").write_text("{}")
    _, failures = run_check(kit, contracts)
    assert any("fps-30/skeleton.json" in f and "missing" in f for f in failures)
    assert any("stale-case/skeleton.json" in f and "not written by any build" in f for f in failures)


def test_ac_k03_a_fault_that_is_gone_from_the_output_fails_and_names_the_take(stand_in_kit, tmp_path):
    kit, _ = copy_kit(stand_in_kit, tmp_path)
    flat = kit / "followers" / "squat_side_shallow_squat" / "skeleton.native.json"
    flat.write_bytes((kit / "followers" / "squat_side_correct" / "skeleton.native.json").read_bytes())
    visible, clean, failures = conformance.check_faults(kit)
    assert visible == 11 and clean == 3
    assert any("squat_side_shallow_squat/skeleton.native.json" in f and "shallow_squat" in f for f in failures)


def test_ac_k03_a_correct_take_that_shows_a_fault_fails(stand_in_kit, tmp_path):
    kit, _ = copy_kit(stand_in_kit, tmp_path)
    faulty = kit / "followers" / "squat_front_feet_wide" / "skeleton.native.json"
    (kit / "followers" / "squat_front_correct" / "skeleton.native.json").write_bytes(faulty.read_bytes())
    visible, clean, failures = conformance.check_faults(kit)
    assert clean == 2
    assert any("squat_front_correct/skeleton.native.json" in f and "feet_wide" in f for f in failures)


def test_ac_k03_a_fault_on_the_wrong_side_fails(stand_in_kit):
    kit, _ = stand_in_kit
    left = next(td for td in followers.take_defs() if td.take_id == "squat_front_knee_caving-left")
    right_take = kit / "followers" / "squat_45_knee_caving-right" / "skeleton.native.json"
    correct = kit / "followers" / "squat_45_correct" / "skeleton.native.json"
    problems = conformance.fault_problems(left, json.loads(right_take.read_text()), json.loads(correct.read_text()), None)
    assert any("left side" in p for p in problems) and any("shows on the right side" in p for p in problems)


def test_a_label_that_disagrees_with_the_output_fails(stand_in_kit, tmp_path):
    kit, contracts = copy_kit(stand_in_kit, tmp_path)
    labels = load_labels(kit)
    labels["takes"][1]["faults"][0]["measured_in_output"] = 0.0999
    io.write_text(kit / "followers" / "labels.json", io.dumps(labels, indent=2))
    visible, _, failures = conformance.check_faults(kit)
    assert visible == 11 and any("measured_in_output" in f for f in failures)


def edit_part5(kit, take_id, edit):
    """Rewrite the part5 `skeleton.json` of a follower take with `edit(joints)` applied to every frame."""
    path = kit / "followers" / take_id / "skeleton.json"
    doc = json.loads(path.read_text())
    for frame in doc["frames"]:
        edit(frame["joints"])
    path.write_text(io.dumps(doc))
    return path


def mirror_x(joints):
    for point in joints.values():
        point[0] = -point[0]


def swap_left_right(joints):
    for name in [n for n in joints if n.startswith("left_")]:
        other = "right_" + name[len("left_"):]
        joints[name], joints[other] = joints[other], joints[name]


def test_r8_the_part5_files_are_measured_too_and_a_clean_kit_passes(stand_in_kit):
    kit, _ = stand_in_kit
    assert conformance.check_faults(kit) == (12, 3, [])
    doc = json.loads((kit / "followers" / "squat_front_feet_wide" / "skeleton.json").read_text())
    assert doc["format"] == "simon.animation.v1" and isinstance(doc["frames"][0]["joints"]["nose"], list)


def test_r8_native_like_gives_the_arrays_the_measures_read(stand_in_kit):
    kit, _ = stand_in_kit
    folder = kit / "followers" / "squat_45_elbows_out"
    native, part5 = json.loads((folder / "skeleton.native.json").read_text()), \
        json.loads((folder / "skeleton.json").read_text())
    converted = conformance.native_like(part5, native)
    assert len(converted["frames"]) == len(native["frames"])
    assert joints_array(converted) == pytest.approx(joints_array(native), abs=1e-12)


def test_r8_a_corrupted_part5_mapping_is_caught_and_the_failure_names_the_part5_file(stand_in_kit, tmp_path):
    kit, _ = copy_kit(stand_in_kit, tmp_path)
    edit_part5(kit, "squat_front_feet_wide", mirror_x)
    visible, clean, failures = conformance.check_faults(kit)
    assert (visible, clean) == (11, 3)
    assert failures and all("followers/squat_front_feet_wide/skeleton.json: " in f for f in failures)
    assert all("skeleton.native.json" not in f for f in failures)  # the native file itself is fine
    assert any("feet_wide" in f for f in failures)


def test_r8_swapped_left_and_right_in_the_part5_file_puts_the_fault_on_the_wrong_side(stand_in_kit, tmp_path):
    kit, _ = copy_kit(stand_in_kit, tmp_path)
    edit_part5(kit, "squat_front_knee_caving-left", swap_left_right)
    visible, _, failures = conformance.check_faults(kit)
    assert visible == 11
    assert any("squat_front_knee_caving-left/skeleton.json" in f and "left side" in f for f in failures)
    assert any("squat_front_knee_caving-left/skeleton.json" in f and "shows on the right side" in f for f in failures)


def test_r8_a_correct_take_whose_part5_file_shows_a_fault_fails(stand_in_kit, tmp_path):
    kit, _ = copy_kit(stand_in_kit, tmp_path)
    faulty = kit / "followers" / "squat_side_shallow_squat" / "skeleton.json"
    (kit / "followers" / "squat_side_correct" / "skeleton.json").write_bytes(faulty.read_bytes())
    _, clean, failures = conformance.check_faults(kit)
    assert clean == 2 and any("squat_side_correct/skeleton.json" in f for f in failures)


def test_r8_a_part5_file_with_other_frames_than_the_native_file_cannot_be_read(stand_in_kit, tmp_path):
    kit, _ = copy_kit(stand_in_kit, tmp_path)
    path = kit / "followers" / "squat_front_correct" / "skeleton.json"
    doc = json.loads(path.read_text())
    del doc["frames"][10]
    path.write_text(io.dumps(doc))
    with pytest.raises(ValueError, match=r"squat_front_correct/skeleton.json: holds \d+ frames with the person"):
        conformance.check_faults(kit)
    metrics, failures = conformance.check(kit, stand_in_kit[1], runner=stand_in, validator=accept_all)
    assert metrics["pass"] is False and any(f.startswith("faults: cannot read the follower outputs") for f in failures)


def test_a_validator_error_names_the_file_and_the_schema(stand_in_kit):
    kit, contracts = stand_in_kit
    metrics, failures = conformance.check(kit, contracts, runner=stand_in,
                                          validator=lambda doc, schema: ["$.frames: bad"] if "bones" in doc else [])
    assert metrics["pass"] is False
    assert any("does not match skeleton.schema.json: $.frames: bad" in f for f in failures)


def test_an_empty_kit_fails_with_messages_not_a_traceback(stand_in_kit, tmp_path):
    _, contracts = stand_in_kit
    metrics, failures = conformance.check(tmp_path / "empty", contracts, runner=stand_in, validator=accept_all)
    assert metrics["pass"] is False and metrics["cases"] == 0 and metrics["files_rebuilt_identical"] == 0
    assert any("cannot rebuild the kit" in f for f in failures) and any("followers/labels.json" in f for f in failures)


def test_a_failing_run_is_reported_with_the_exit_code_and_message(stand_in_kit, tmp_path):
    kit, _ = copy_kit(stand_in_kit, tmp_path)
    failures = conformance.generate_outputs(kit, tmp_path / "out", lambda args: (2, "bad option"))
    assert failures and all("exited 2: bad option" in f for f in failures)


# ---- the real kit, once the tree is integrated ------------------------------------------------------

def test_ac_k01_make_check_3_contract_passes_on_the_committed_kit():
    pytest.importorskip("part3.jsonschema_lite")
    pytest.importorskip("part3.views")
    pytest.importorskip("part3.profiles")
    if not (ROOT / "contracts").is_dir() or not (KIT / "golden" / "default" / "skeleton.json").is_file():
        pytest.skip("contracts/ or the committed goldens are not in this tree yet")
    done = subprocess.run([sys.executable, "-m", "part3.conformance", "check"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    metrics = json.loads(done.stdout)
    assert metrics["pass"] is True and metrics["faults_visible"] == 12 and metrics["correct_takes_clean"] == 3
