"""Input adapters (spec integration-contract.md "Input adapters"; AC-A01, AC-A02, AC-V05)."""

import copy
import json

import pytest

from part3 import adapters, cli
from part3.adapters import derive_t_ms, extra_joints, flat_joints, frame_index, joint_arrays
from part3.joints import JOINTS
from part3.schema import ContractError, validate_pose3d

CLEAN = {"env": {}, "config": False}
ORDER = ["flat-joints", "joint-arrays", "extra-joints", "frame-index", "derive-t_ms"]


@pytest.fixture
def doc(real_doc):
    """A private 12-frame copy of the real clip."""
    small = copy.deepcopy(real_doc)
    small["frames"] = small["frames"][:12]
    return small


def arrays(joints, with_conf=True):
    return {name: [j["x"], j["y"], j["z"]] + ([j["conf"]] if with_conf else []) for name, j in joints.items()}


def as_arrays(doc, with_conf=True):
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        for person in frame["people"]:
            person["joints"] = arrays(person["joints"], with_conf)
    return out


def flat(doc):
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        frame["joints"] = frame.pop("people")[0]["joints"]
    return out


def process(candidate, **kw):
    return cli.process(candidate, **CLEAN, **kw)


def same_but_adapters(a, b):
    a, b = copy.deepcopy(a), copy.deepcopy(b)
    a["input"].pop("adapters"), b["input"].pop("adapters")
    a["input"].pop("sha256"), b["input"].pop("sha256")
    return a == b


# --- the registry ---------------------------------------------------------------------------------

def test_registry_order_and_module_contract():
    assert [m.NAME for m in adapters.REGISTRY] == ORDER
    for module in adapters.REGISTRY:
        assert module.DESCRIPTION and callable(module.applies) and callable(module.apply)


def test_ac_a01_a_canonical_part2_file_fires_nothing_and_is_returned_as_is(doc):
    adapted, names = adapters.adapt(doc)
    assert names == [] and adapted is doc
    assert process(doc)["input"]["adapters"] == []


def test_ac_a01_the_real_fixture_native_output_is_unchanged_apart_from_the_two_blocks(real_doc):
    skeleton = process(real_doc)
    assert skeleton["input"]["adapters"] == [] and skeleton["body"]["profile"] == "simon-standard"


def test_adapt_never_mutates_its_input(doc):
    messy = flat(as_arrays(doc))
    for frame in messy["frames"]:
        del frame["frame"], frame["t_ms"]
        frame["joints"]["tail"] = [0.0, 0.0, 0.0]
    before = copy.deepcopy(messy)
    adapters.adapt(messy, input_fps=15)
    assert messy == before


# --- each adapter fires only on its shape -----------------------------------------------------------

def test_ac_a01_flat_joints_fires_on_a_frame_with_joints_and_no_people(doc):
    assert not flat_joints.applies(doc) and flat_joints.applies(flat(doc))
    adapted, names = adapters.adapt(flat(doc))
    assert names == ["flat-joints"]
    assert [f["people"][0]["id"] for f in adapted["frames"]] == [0] * 12
    assert all("joints" not in f for f in adapted["frames"])
    validate_pose3d(adapted)
    assert same_but_adapters(process(flat(doc)), process(doc))


def test_flat_joints_leaves_a_frame_that_has_people_alone(doc):
    mixed = flat(doc)
    mixed["frames"][3] = doc["frames"][3]
    adapted, _ = adapters.adapt(mixed)
    assert adapted["frames"][3] == doc["frames"][3]


def test_ac_a01_joint_arrays_with_and_without_conf(doc):
    assert not joint_arrays.applies(doc) and joint_arrays.applies(as_arrays(doc))
    adapted, names = adapters.adapt(as_arrays(doc))
    assert names == ["joint-arrays"] and adapted == doc
    no_conf, names = adapters.adapt(as_arrays(doc, with_conf=False))
    assert names == ["joint-arrays"]
    assert {j["conf"] for p in no_conf["frames"][0]["people"] for j in p["joints"].values()} == {1.0}
    validate_pose3d(no_conf)


def test_ac_a02_a_list_of_17_arrays_in_canonical_order(doc):
    listed = as_arrays(doc)
    for frame in listed["frames"]:
        person = frame["people"][0]
        person["joints"] = [person["joints"][name] for name in JOINTS]
    assert joint_arrays.applies(listed)
    adapted, names = adapters.adapt(listed)
    assert names == ["joint-arrays"] and adapted == doc


def test_a_list_of_the_wrong_length_is_left_for_the_validator(doc):
    listed = as_arrays(doc)
    listed["frames"] = listed["frames"][:1]
    listed["frames"][0]["people"][0]["joints"] = [[0.0, 0.0, 0.0]] * 16
    assert not joint_arrays.applies(listed)
    with pytest.raises(ContractError) as caught:
        process(listed)
    assert caught.value.path == "pose3d.frames[0].people[0].joints"


def test_ac_a02_extra_joint_names_are_dropped_but_a_missing_one_still_fails(doc):
    plus = copy.deepcopy(doc)
    for frame in plus["frames"]:
        frame["people"][0]["joints"]["neck_extra"] = {"x": 0, "y": 0, "z": 0, "conf": 1}
        frame["people"][0]["joints"]["mid_hip"] = [0, 0, 0]
    assert not extra_joints.applies(doc) and extra_joints.applies(plus)
    adapted, names = adapters.adapt(plus)
    assert names == ["joint-arrays", "extra-joints"] and adapted == doc
    missing = copy.deepcopy(plus)
    del missing["frames"][2]["people"][0]["joints"]["nose"]
    with pytest.raises(ContractError) as caught:
        process(missing)
    assert caught.value.path == "pose3d.frames[2].people[0].joints" and "missing nose" in str(caught.value)


def test_ac_a02_frames_without_frame_get_their_position(doc):
    bare = copy.deepcopy(doc)
    for frame in bare["frames"]:
        del frame["frame"]
    assert not frame_index.applies(doc) and frame_index.applies(bare)
    adapted, names = adapters.adapt(bare)
    assert names == ["frame-index"] and adapted == doc


def test_ac_a02_t_ms_is_derived_from_input_fps_or_a_top_level_fps(doc):
    bare = copy.deepcopy(doc)
    for frame in bare["frames"]:
        del frame["t_ms"]
    assert not derive_t_ms.applies(doc) and derive_t_ms.applies(bare)
    adapted, names = adapters.adapt(bare, input_fps=15)
    assert names == ["derive-t_ms"]
    assert [f["t_ms"] for f in adapted["frames"]] == [f["t_ms"] for f in doc["frames"]]  # 66.667 and so on
    with_top = dict(bare, fps=15)
    assert [f["t_ms"] for f in adapters.adapt(with_top)[0]["frames"]] == [f["t_ms"] for f in doc["frames"]]
    assert adapters.adapt(with_top, input_fps=30)[0]["frames"][3]["t_ms"] == 100.0  # the option beats the file
    assert same_but_adapters(process(bare, input_fps="15"), process(doc))


def test_ac_a02_no_t_ms_and_no_fps_names_input_fps(doc):
    bare = copy.deepcopy(doc)
    for frame in bare["frames"]:
        del frame["t_ms"]
    for extra in ({}, {"fps": "fast"}, {"fps": 0}, {"fps": True}, {"fps": -3}):
        with pytest.raises(ContractError) as caught:
            process(dict(bare, **extra))
        assert str(caught.value) == "pose3d.frames[0].t_ms: missing; pass --input-fps <n> or add a top-level fps"


def test_the_derive_error_names_the_first_frame_missing_t_ms(doc):
    bare = copy.deepcopy(doc)
    del bare["frames"][4]["t_ms"]
    with pytest.raises(ContractError) as caught:
        process(bare)
    assert caught.value.path == "pose3d.frames[4].t_ms"


@pytest.mark.parametrize("bad", [0, -1, "x", True, float("nan"), float("inf"), []])
def test_a_bad_input_fps_names_the_option(doc, bad):
    with pytest.raises(ContractError) as caught:
        adapters.adapt(doc, input_fps=bad)
    assert str(caught.value).startswith("--input-fps: must be a positive number")


# --- combinations run end to end and are named in order -----------------------------------------------

def test_ac_a02_every_shape_at_once_runs_and_names_the_adapters_in_order(doc):
    messy = flat(as_arrays(doc, with_conf=False))
    for frame in messy["frames"]:
        del frame["frame"], frame["t_ms"]
        frame["joints"]["tail"] = [1.0, 2.0, 3.0]
    skeleton = process(messy, input_fps=15)
    assert skeleton["input"]["adapters"] == ORDER
    expected = process(doc)
    assert [f["frame"] for f in skeleton["frames"]] == [f["frame"] for f in expected["frames"]]
    assert [f["t_ms"] for f in skeleton["frames"]] == [f["t_ms"] for f in expected["frames"]]


def test_the_written_file_records_the_adapters(doc, tmp_path):
    source, out = tmp_path / "in.json", tmp_path / "out.json"
    source.write_text(json.dumps(as_arrays(doc)))
    assert cli.main(["run", "--in", str(source), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["input"]["adapters"] == ["joint-arrays"]


def test_json_that_is_not_an_object_is_left_to_the_validator():
    for value in (None, [], "x", 3):
        assert adapters.adapt(value) == (value, [])
    assert adapters.adapt({"frames": "no"}) == ({"frames": "no"}, [])
    assert adapters.adapt({"frames": [1, None]}) == ({"frames": [1, None]}, [])


# --- AC-V05: a new adapter is one module and one registry entry --------------------------------------

def test_ac_v05_a_dummy_adapter_registered_in_one_line_fires_and_is_named(doc, monkeypatch):
    class Dummy:
        NAME = "dummy-id"
        DESCRIPTION = "ids given as text become integers"

        @staticmethod
        def applies(candidate):
            return any(isinstance(p["id"], str) for f in candidate["frames"] for p in f["people"])

        @staticmethod
        def apply(candidate, input_fps=None):
            out = copy.deepcopy(candidate)
            for frame in out["frames"]:
                for person in frame["people"]:
                    person["id"] = int(person["id"])
            return out

    texty = copy.deepcopy(doc)
    for frame in texty["frames"]:
        frame["people"][0]["id"] = "5"
    monkeypatch.setattr(adapters, "REGISTRY", adapters.REGISTRY + [Dummy])
    skeleton = process(texty)
    assert skeleton["input"]["adapters"] == ["dummy-id"] and skeleton["person"]["id"] == 5


def test_b5_the_adapters_use_the_shared_number_test_and_keep_its_rules(doc):
    from part3 import schema
    assert adapters.is_number is schema.is_number and not hasattr(adapters, "_is_number")
    no_t = {"fps": True, "frames": [{k: v for k, v in f.items() if k != "t_ms"} for f in doc["frames"]]}
    with pytest.raises(ContractError, match=r"pose3d\.frames\[0\]\.t_ms: missing; pass --input-fps"):
        cli.process(no_t, **CLEAN)  # a boolean is not a frame rate
    no_t["fps"] = 15
    assert cli.process(no_t, **CLEAN)["input"]["adapters"] == ["derive-t_ms"]
