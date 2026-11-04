"""The body default of the part4 view (spec integration-contract.md AC-B07, assumption ASM-012, TICKET-035).

With no body named on any channel, `--view part4` is rebuilt on `part4-rig`, because Part 4's animator rejects bone
lengths more than 1 mm off its rig, and the output says why in `body.reason`. A body named on any channel wins and
records no reason. Every other view keeps `simon-standard` (ASM-013).
"""

import copy
import json
import pathlib

import pytest

from conftest import REAL_CLIP
from part3 import cli, profiles, runapi
from part3.schema import ContractError, validate_skeleton
from runapikit import options_for

REASON = profiles.VIEW_DEFAULTS["part4"][1]


@pytest.fixture(autouse=True)
def quiet_environment(tmp_path, monkeypatch):
    """No profile channel from the machine: no PART3_* variables and no part3.toml in the working directory."""
    for key in ("PART3_BODY", "PART3_STATURE", "PART3_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def body_of_run(tmp_path, *options):
    target = tmp_path / "out.json"
    assert cli.main(["run", "--in", str(REAL_CLIP), "--out", str(target), *options]) == 0
    return json.loads(pathlib.Path(target).read_text())["body"]


PART4 = ("--view", "part4", "--keyframes", "every:10")


# ---- resolve -----------------------------------------------------------------------------------

def test_the_part4_view_defaults_to_the_part4_rig_and_says_why():
    picked = profiles.resolve(env={}, config=False, view="part4")
    assert (picked.name, picked.selected_by, picked.spec, picked.reason) == ("part4-rig", "default", "part4-rig", REASON)
    assert "Part 4's animator rejects bone lengths more than 1 mm off its rig" in REASON and "ASM-012" in REASON


@pytest.mark.parametrize("view", [None, "native", "part5"])
def test_every_other_view_keeps_simon_standard_with_no_reason(view):
    picked = profiles.resolve(env={}, config=False, view=view)
    assert (picked.name, picked.selected_by, picked.reason) == ("simon-standard", "default", None)


def test_a_body_named_on_any_channel_wins_over_the_part4_default(tmp_path):
    config = tmp_path / "part3.toml"
    config.write_text('[body]\nprofile = "measured"\n', encoding="utf-8")
    picks = [
        profiles.resolve(flag="simon-standard", env={}, config=False, view="part4"),
        profiles.resolve(env={"PART3_BODY": "simon-standard"}, config=False, view="part4"),
        profiles.resolve(env={}, config=config, view="part4"),
        profiles.resolve(api="simon-standard", env={}, config=False, view="part4"),
    ]
    assert [(p.name, p.selected_by, p.reason) for p in picks] == [
        ("simon-standard", "flag", None), ("simon-standard", "env", None), ("measured", "config", None),
        ("simon-standard", "api", None)]


def test_a_stature_alone_does_not_name_a_body():
    picked = profiles.resolve(stature_flag="1.85", env={}, config=False, view="part4")
    assert (picked.name, picked.selected_by, picked.stature, picked.reason) == ("part4-rig", "default", 1.85, REASON)


# ---- the command line --------------------------------------------------------------------------

def test_the_command_line_part4_view_is_rebuilt_on_the_part4_rig_with_the_reason(tmp_path):
    body = body_of_run(tmp_path, *PART4)
    assert (body["profile"], body["selected_by"], body["reason"]) == ("part4-rig", "default", REASON)


def test_a_named_body_on_the_command_line_wins_and_records_no_reason(tmp_path):
    body = body_of_run(tmp_path, *PART4, "--body", "simon-standard")
    assert (body["profile"], body["selected_by"]) == ("simon-standard", "flag") and "reason" not in body


def test_the_environment_wins_over_the_part4_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PART3_BODY", "measured")
    body = body_of_run(tmp_path, *PART4)
    assert (body["profile"], body["selected_by"]) == ("measured", "env") and "reason" not in body


@pytest.mark.parametrize("view", [(), ("--view", "native"), ("--view", "part5")])
def test_the_other_views_on_the_command_line_keep_simon_standard(tmp_path, view):
    body = body_of_run(tmp_path, *view)
    assert (body["profile"], body["selected_by"]) == ("simon-standard", "default") and "reason" not in body


# ---- the run app -------------------------------------------------------------------------------

@pytest.mark.parametrize("query, profile, selected_by", [
    ("view=part4", "part4-rig", "default"), ("body=&view=part4", "part4-rig", "default"),
    ("body=simon-standard&view=part4", "simon-standard", "flag"), ("view=part5", "simon-standard", "default"),
    ("", "simon-standard", "default"),
])
def test_the_run_app_takes_the_same_default_and_echoes_the_body_that_ran(query, profile, selected_by):
    status, reply = runapi.handle("part2-squat", "auto", None, b"", options_for(query))
    native = json.loads(reply["skeleton_text"])["body"]
    assert status == 200 and (native["profile"], native["selected_by"]) == (profile, selected_by)
    assert reply["options"]["body"] == profile and reply["metrics"]["profile"] == profile
    assert ("reason" in native) is (selected_by == "default" and profile == "part4-rig")


def test_the_run_app_part4_download_equals_the_command_line_without_body(tmp_path):
    status, reply = runapi.handle("part2-squat", "auto", None, b"", options_for("view=part4"))
    target = tmp_path / "cli.json"
    source = runapi.sample_input("part2-squat")[1]
    (tmp_path / "in.json").write_bytes(source)
    assert cli.main(["run", "--in", str(tmp_path / "in.json"), "--out", str(target), *PART4]) == 0
    assert status == 200 and reply["output_text"].encode() == target.read_bytes()


# ---- the block validator -----------------------------------------------------------------------

def part4_default_skeleton():
    return cli.process(json.loads(REAL_CLIP.read_text()), body=profiles.resolve(env={}, config=False, view="part4"),
                       env={}, config=False)


def test_a_part4_default_skeleton_validates():
    skeleton = part4_default_skeleton()
    assert skeleton["body"]["reason"] == REASON
    validate_skeleton(skeleton)


@pytest.mark.parametrize("mutate", [
    lambda body: body.update(selected_by="flag"),  # a reason on a body a channel chose
    lambda body: body.update(reason=""),
    lambda body: body.update(reason=7),
])
def test_the_validator_rejects_a_reason_that_does_not_belong(mutate):
    broken = copy.deepcopy(part4_default_skeleton())
    mutate(broken["body"])
    with pytest.raises(ContractError) as caught:
        validate_skeleton(broken)
    assert caught.value.path == "skeleton.body.reason"
