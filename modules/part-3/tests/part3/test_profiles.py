"""Body profiles (spec integration-contract.md "Body profiles"; AC-B01 to AC-B06)."""

import copy
import json

import pytest

from clipkit import skeleton_arrays, write_profile
from part3 import bones, cli, profiles, runapi
from part3.joints import BONE_NAMES
from part3.metrics import bone_variation
from part3.schema import ContractError, validate_skeleton
from part3.standard import bone_lengths, sources, stature_m

LIMIT = 0.02
CLEAN = {"env": {}, "config": False}


def run(doc, **kw):
    return cli.process(doc, **{**CLEAN, **kw})


def variation(skeleton):
    return bone_variation(skeleton, bones.lengths_array(skeleton["bone_lengths_m"]))


# --- AC-B01: the default ------------------------------------------------------------------------

def test_ac_b01_default_profile_is_simon_standard_selected_by_default(real_doc):
    skeleton = run(real_doc)
    assert skeleton["body"] == {"profile": "simon-standard", "selected_by": "default", "stature_m": 1.7,
                                "scale": 1.0, "source": "part3/standard_body.json", "symmetrized": False}
    assert skeleton["bone_lengths_m"] == bone_lengths()
    assert skeleton["standard"] == {"stature_m": stature_m(), "sources": sources()}


# --- AC-B02: each profile gives its own numbers ---------------------------------------------------

def test_ac_b02_part4_rig_numbers_and_source(real_doc):
    skeleton = run(real_doc, body="part4-rig")
    assert skeleton["bone_lengths_m"] == profiles.PART4_LENGTHS_M
    assert skeleton["bone_lengths_m"]["left_thigh"] == 0.4165 and skeleton["bone_lengths_m"]["spine"] == 0.4896
    assert skeleton["body"]["profile"] == "part4-rig" and skeleton["body"]["selected_by"] == "api"
    assert "simon-part-4-animate-keyframes 9f4c073" in skeleton["body"]["source"]
    assert skeleton["standard"]["sources"] == [skeleton["body"]["source"]]
    assert skeleton["standard"]["stature_m"] == 1.7
    assert variation(skeleton) < LIMIT
    validate_skeleton(skeleton)


def test_ac_b02_part4_rig_has_all_18_bones_with_equal_pelvis_and_clavicle_halves():
    assert list(profiles.PART4_LENGTHS_M) == list(BONE_NAMES)
    assert profiles.PART4_LENGTHS_M["left_pelvis"] == profiles.PART4_LENGTHS_M["right_pelvis"]
    assert profiles.PART4_LENGTHS_M["left_clavicle"] == profiles.PART4_LENGTHS_M["right_clavicle"]


def test_ac_b02_measured_numbers_source_and_variation(real_doc):
    skeleton = run(real_doc, body="measured")
    assert skeleton["body"]["profile"] == "measured" and skeleton["body"]["symmetrized"] is True
    assert skeleton["body"]["source"] == "measured: median input bone lengths of this clip"
    assert skeleton["standard"]["sources"] == [skeleton["body"]["source"]]
    assert variation(skeleton) < LIMIT
    validate_skeleton(skeleton)


def test_ac_b02_a_valid_file_profile_gives_its_numbers(real_doc, tmp_path):
    path = write_profile(tmp_path / "tall.json")
    skeleton = run(real_doc, body=f"file:{path}")
    expected = json.loads(path.read_text())
    assert skeleton["bone_lengths_m"] == expected["bone_lengths_m"]
    assert skeleton["body"]["profile"] == "file:tall-test" and skeleton["body"]["stature_m"] == 1.9
    assert skeleton["body"]["source"] == f"unit test (file:{path})"
    assert skeleton["standard"]["stature_m"] == 1.9
    assert variation(skeleton) < LIMIT
    validate_skeleton(skeleton)


# --- AC-B03: --stature --------------------------------------------------------------------------

def test_ac_b03_stature_scales_every_length_and_records_the_scale(real_doc):
    skeleton = run(real_doc, stature=1.85)
    scale = 1.85 / 1.70
    assert skeleton["body"]["scale"] == pytest.approx(scale, abs=1e-12)
    assert skeleton["body"]["stature_m"] == 1.85 and skeleton["standard"]["stature_m"] == 1.85
    for name, value in bone_lengths().items():
        assert skeleton["bone_lengths_m"][name] == pytest.approx(value * scale, abs=5e-5)
    assert skeleton["body"]["stature_selected_by"] == "api"
    assert variation(skeleton) < LIMIT
    validate_skeleton(skeleton)


def test_stature_selected_by_is_absent_when_no_stature_was_asked_for(real_doc):
    assert "stature_selected_by" not in run(real_doc)["body"]


def test_ac_b03_stature_scales_the_measured_lengths(real_doc):
    plain, scaled = run(real_doc, body="measured"), run(real_doc, body="measured", stature=1.5)
    scale = 1.5 / plain["body"]["stature_m"]
    assert scaled["body"]["scale"] == pytest.approx(scale) and scaled["body"]["symmetrized"] is True
    for name in BONE_NAMES:
        assert scaled["bone_lengths_m"][name] == pytest.approx(plain["bone_lengths_m"][name] * scale, abs=5e-5)
    validate_skeleton(scaled)


# --- AC-B04: precedence -------------------------------------------------------------------------

def toml(tmp_path, text):
    path = tmp_path / "part3.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_ac_b04_the_body_precedence_is_flag_env_config_api_default(tmp_path):
    path = toml(tmp_path, '[body]\nprofile = "measured"\n')
    env = {"PART3_BODY": "part4-rig"}
    everything = profiles.resolve(flag="simon-standard", api="measured", env=env, config=path)
    assert (everything.name, everything.selected_by) == ("simon-standard", "flag")
    no_flag = profiles.resolve(api="simon-standard", env=env, config=path)
    assert (no_flag.name, no_flag.selected_by) == ("part4-rig", "env")
    no_env = profiles.resolve(api="part4-rig", env={}, config=path)
    assert (no_env.name, no_env.selected_by) == ("measured", "config")
    api_only = profiles.resolve(api="part4-rig", env={}, config=False)
    assert (api_only.name, api_only.selected_by) == ("part4-rig", "api")
    nothing = profiles.resolve(env={}, config=False)
    assert (nothing.name, nothing.selected_by, nothing.spec) == ("simon-standard", "default", "simon-standard")


def test_ac_b04_the_stature_precedence_is_flag_env_config_api_none(tmp_path):
    path = toml(tmp_path, "[body]\nstature = 1.6\n")
    env = {"PART3_STATURE": "1.7"}
    picks = [
        profiles.resolve(stature_flag="1.8", stature_api=1.5, env=env, config=path),
        profiles.resolve(stature_api=1.5, env=env, config=path),
        profiles.resolve(stature_api=1.5, env={}, config=path),
        profiles.resolve(stature_api=1.5, env={}, config=False),
        profiles.resolve(env={}, config=False),
    ]
    assert [(p.stature, p.stature_selected_by) for p in picks] == [
        (1.8, "flag"), (1.7, "env"), (1.6, "config"), (1.5, "api"), (None, None)]


def test_ac_b04_each_channel_is_recorded_in_the_output(real_doc, tmp_path):
    path = toml(tmp_path, '[body]\nprofile = "part4-rig"\nstature = 1.6\n')
    from_config = cli.process(real_doc, env={}, config=path)
    assert from_config["body"]["selected_by"] == "config" and from_config["body"]["stature_selected_by"] == "config"
    from_env = cli.process(real_doc, env={"PART3_BODY": "measured", "PART3_STATURE": "1.7"}, config=False)
    assert from_env["body"]["selected_by"] == "env" and from_env["body"]["stature_selected_by"] == "env"
    selection = profiles.resolve(flag="part4-rig", stature_flag=1.9, env={}, config=False)
    from_flag = cli.process(real_doc, body=selection)
    assert from_flag["body"]["selected_by"] == "flag" and from_flag["body"]["stature_selected_by"] == "flag"


def test_ac_b04_an_empty_environment_variable_counts_as_unset():
    picked = profiles.resolve(env={"PART3_BODY": "", "PART3_STATURE": ""}, config=False)
    assert (picked.selected_by, picked.stature) == ("default", None)


def test_ac_b04_a_relative_file_path_in_a_config_file_follows_that_file(real_doc, tmp_path, monkeypatch):
    folder = tmp_path / "conf"
    folder.mkdir()
    write_profile(folder / "mine.json")
    path = folder / "part3.toml"
    path.write_text('[body]\nprofile = "file:mine.json"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # elsewhere than the config file's folder
    skeleton = cli.process(real_doc, env={}, config=path)
    assert skeleton["body"]["profile"] == "file:tall-test" and skeleton["body"]["selected_by"] == "config"
    with pytest.raises(ContractError):  # the same relative path from the flag means the working directory
        cli.process(real_doc, body="file:mine.json", env={}, config=False)


# --- AC-B05: errors name the channel and the field ------------------------------------------------

def refusal(doc, **kw):
    with pytest.raises(ContractError) as caught:
        run(doc, **kw)
    return caught.value


@pytest.mark.parametrize("kw,env,channel", [
    ({"body": "bespoke"}, {}, "body="),
    ({}, {"PART3_BODY": "bespoke"}, "PART3_BODY"),
    ({"body": "file:"}, {}, "body="),
])
def test_ac_b05_an_unknown_profile_names_the_channel(real_doc, kw, env, channel):
    error = refusal(real_doc, env=env, **kw)
    assert str(error).startswith(f"{channel}: unknown body profile")
    assert "simon-standard, part4-rig, measured or file:<path>" in str(error)


def test_ac_b05_flag_and_config_channels_are_named(tmp_path):
    with pytest.raises(ContractError) as flag:
        profiles.resolve(flag="bespoke", env={}, config=False)
    assert str(flag.value).startswith("--body: unknown body profile \"bespoke\"")
    path = toml(tmp_path, '[body]\nprofile = "bespoke"\n')
    with pytest.raises(ContractError) as in_config:
        profiles.resolve(env={}, config=path)
    assert "body.profile: unknown body profile" in str(in_config.value) and str(path) in str(in_config.value)


@pytest.mark.parametrize("value", [0.49, 2.51, "tall", float("nan"), True, "inf"])
def test_ac_b05_a_stature_out_of_range_names_the_channel(value):
    with pytest.raises(ContractError) as flag:
        profiles.resolve(stature_flag=value, env={}, config=False)
    assert str(flag.value).startswith("--stature: stature must be 0.5 to 2.5 m (got ")
    with pytest.raises(ContractError) as env:
        profiles.resolve(env={"PART3_STATURE": str(value)}, config=False)
    assert str(env.value).startswith("PART3_STATURE: ")
    with pytest.raises(ContractError) as api:
        profiles.resolve(stature_api=value, env={}, config=False)
    assert str(api.value).startswith("stature=: ")


def test_ac_b05_the_stature_limits_themselves_are_accepted():
    assert profiles.resolve(stature_flag="0.5", env={}, config=False).stature == 0.5
    assert profiles.resolve(stature_flag=2.5, env={}, config=False).stature == 2.5


def test_ac_b05_a_stature_in_a_config_file_names_the_file(tmp_path):
    path = toml(tmp_path, "[body]\nstature = 9\n")
    with pytest.raises(ContractError) as caught:
        profiles.resolve(env={}, config=path)
    assert "body.stature: stature must be 0.5 to 2.5 m (got 9)" in str(caught.value)


def test_ac_b05_a_bad_toml_file_stops_the_run(real_doc, tmp_path):
    path = toml(tmp_path, "[body\n")
    with pytest.raises(ContractError) as caught:
        cli.process(real_doc, env={}, config=path)
    assert "not valid TOML" in str(caught.value)


def profile_error(real_doc, tmp_path, **changes):
    path = write_profile(tmp_path / "p.json", **changes)
    with pytest.raises(ContractError) as caught:
        run(real_doc, body=f"file:{path}")
    return str(caught.value), path


def test_ac_b05_a_file_profile_missing_a_bone_names_the_bone(real_doc, tmp_path):
    lengths = dict(bone_lengths())
    del lengths["left_thigh"]
    message, path = profile_error(real_doc, tmp_path, bone_lengths_m=lengths)
    assert message == f"body file:{path}: bone_lengths_m.left_thigh: missing"


def test_ac_b05_a_file_profile_with_unequal_pelvis_halves_names_the_bone(real_doc, tmp_path):
    lengths = dict(bone_lengths(), right_pelvis=0.13)
    message, path = profile_error(real_doc, tmp_path, bone_lengths_m=lengths)
    assert message.startswith(f"body file:{path}: bone_lengths_m.right_pelvis: must equal left_pelvis")


def test_ac_b05_a_file_profile_with_unequal_clavicles_names_the_bone(real_doc, tmp_path):
    lengths = dict(bone_lengths(), left_clavicle=0.2)
    message, _ = profile_error(real_doc, tmp_path, bone_lengths_m=lengths)
    assert "bone_lengths_m.right_clavicle: must equal left_clavicle" in message


@pytest.mark.parametrize("bad", ["long", None, 0.004, 1.6, float("inf"), -0.4, True, 10 ** 400])
def test_ac_b05_a_file_profile_with_a_bad_number_names_the_bone(real_doc, tmp_path, bad):
    lengths = dict(bone_lengths(), left_thigh=bad)
    path = tmp_path / "p.json"
    write_profile(path)
    document = json.loads(path.read_text())
    document["bone_lengths_m"] = lengths
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ContractError) as caught:
        run(real_doc, body=f"file:{path}")
    assert f"body file:{path}: bone_lengths_m.left_thigh: " in str(caught.value)


def test_ac_b05_a_file_profile_with_an_unknown_bone_or_bad_stature_or_fields(real_doc, tmp_path):
    message, _ = profile_error(real_doc, tmp_path, bone_lengths_m=dict(bone_lengths(), tail=0.3))
    assert "bone_lengths_m.tail: unknown bone" in message
    message, _ = profile_error(real_doc, tmp_path, stature_m=3.0)
    assert "stature_m: 3.0 is not between 0.5 and 2.5 m" in message
    message, _ = profile_error(real_doc, tmp_path, schema="other/1")
    assert 'schema: expected "simon.body_profile/1"' in message
    message, _ = profile_error(real_doc, tmp_path, name="")
    assert "name: expected a non-empty string" in message
    message, _ = profile_error(real_doc, tmp_path, source=None)
    assert "source: expected a non-empty string" in message
    message, _ = profile_error(real_doc, tmp_path, bone_lengths_m=[1, 2])
    assert "bone_lengths_m: expected an object" in message


def test_ac_b05_an_unreadable_or_non_json_file_profile_is_named(real_doc, tmp_path):
    with pytest.raises(ContractError) as missing:
        run(real_doc, body=f"file:{tmp_path / 'nope.json'}")
    assert "cannot read" in str(missing.value) and "nope.json" in str(missing.value)
    junk = tmp_path / "junk.json"
    junk.write_text("{not json")
    with pytest.raises(ContractError) as bad:
        run(real_doc, body=f"file:{junk}")
    assert "not valid JSON" in str(bad.value)
    listing = tmp_path / "list.json"
    listing.write_text("[]")
    with pytest.raises(ContractError) as wrong:
        run(real_doc, body=f"file:{listing}")
    assert "expected an object" in str(wrong.value)


# --- AC-B06: measured ---------------------------------------------------------------------------

def test_ac_b06_measured_lengths_are_the_symmetrized_medians(real_doc):
    skeleton = run(real_doc, body="measured")
    measured = skeleton["person"]["measured_bone_lengths_m"]
    lengths = skeleton["bone_lengths_m"]
    assert measured["left_thigh"] != measured["right_thigh"]  # the clip really is asymmetric
    for name in BONE_NAMES:
        if name.startswith("left_"):
            twin = "right_" + name[len("left_"):]
            assert lengths[name] == lengths[twin] == pytest.approx((measured[name] + measured[twin]) / 2, abs=5e-5)
        elif not name.startswith("right_"):
            assert lengths[name] == measured[name]


def test_ac_b06_measured_lengths_are_the_same_in_every_frame(real_doc):
    skeleton = run(real_doc, body="measured")
    lengths = bones.lengths_array(skeleton["bone_lengths_m"])
    J, _, present = skeleton_arrays(skeleton)
    seen = bones.measure(J[present])
    assert present.all() and abs(seen - lengths).max() < 1.5e-4  # the 4-decimal rounding of the coordinates


def test_measured_stature_is_the_chain_estimate_the_run_page_uses(real_doc):
    skeleton = run(real_doc, body="measured")
    standard_skeleton = run(real_doc)
    page = runapi.handle(None, "auto", None, json.dumps(real_doc).encode())[1]["metrics"]["input_height_estimate_m"]
    unsym = profiles.estimate_stature(standard_skeleton["person"]["measured_bone_lengths_m"])
    assert unsym == pytest.approx(page, abs=1e-4)  # the run page shows this estimate, rounded to 4 decimals
    assert skeleton["body"]["stature_m"] == pytest.approx(profiles.estimate_stature(skeleton["bone_lengths_m"]), abs=1e-4)


def test_measured_needs_the_measured_lengths():
    selection = profiles.resolve(flag="measured", env={}, config=False)
    with pytest.raises(ContractError):
        profiles.lengths_for(selection, None)
    broken = dict(bone_lengths(), head=0.0)
    with pytest.raises(ContractError) as caught:
        profiles.lengths_for(selection, broken)
    assert "body measured: bone_lengths_m.head: 0.0 is not between 0.005 and 1.5 m" in str(caught.value)


# --- the Body object and the block validator ------------------------------------------------------

def test_lengths_for_returns_a_private_copy_and_every_field():
    selection = profiles.resolve(env={}, config=False)
    body = profiles.lengths_for(selection)
    body.bone_lengths_m["left_thigh"] = 9.0
    body.sources.append("x")
    again = profiles.lengths_for(selection)
    assert again.bone_lengths_m == bone_lengths() and again.sources == sources()
    assert (again.name, again.stature_m, again.scale, again.symmetrized, again.selected_by) == (
        "simon-standard", 1.7, 1.0, False, "default")


def test_the_validator_rejects_a_body_block_that_does_not_match_its_numbers(real_doc):
    skeleton = run(real_doc, body="part4-rig")
    for mutate, path in [
        (lambda s: s["body"].update(selected_by="cli"), "skeleton.body.selected_by"),
        (lambda s: s["body"].update(scale=0), "skeleton.body.scale"),
        (lambda s: s["body"].update(profile="bespoke"), "skeleton.body.profile"),
        (lambda s: s["body"].update(symmetrized=1), "skeleton.body.symmetrized"),
        (lambda s: s["body"].update(source=""), "skeleton.body.source"),
        (lambda s: s["body"].update(stature_selected_by="default"), "skeleton.body.stature_selected_by"),
        (lambda s: s["body"].update(scale=1.5), "skeleton.bone_lengths_m"),
        (lambda s: s["bone_lengths_m"].update(right_pelvis=0.2), "skeleton.bone_lengths_m.right_pelvis"),
        (lambda s: s.update(body="x"), "skeleton.body"),
    ]:
        broken = copy.deepcopy(skeleton)
        mutate(broken)
        with pytest.raises(ContractError) as caught:
            validate_skeleton(broken)
        assert caught.value.path == path


def test_a_skeleton_from_before_the_body_block_stays_valid(real_doc):
    skeleton = run(real_doc)
    del skeleton["body"]
    del skeleton["input"]["adapters"]
    validate_skeleton(skeleton)
    skeleton["bone_lengths_m"]["left_thigh"] = 0.5
    with pytest.raises(ContractError):
        validate_skeleton(skeleton)


def test_every_profile_stays_under_the_bone_variation_limit_on_a_synthetic_take():
    from conftest import SYNTH_DIR

    doc = json.loads((SYNTH_DIR / "take-2" / "pose3d.json").read_text())
    for body in ("simon-standard", "part4-rig", "measured"):
        assert variation(run(doc, body=body)) < LIMIT
