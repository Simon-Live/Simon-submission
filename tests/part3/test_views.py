"""The view registry, the native view and the part5 view (spec integration-contract.md "Views"; AC-V04, AC-V05)."""

import copy
import json
import pathlib
import types

import pytest

from part3 import cli, contract, jsonschema_lite, views
from part3.views import part5
from part3.joints import JOINTS
from part3.schema import SCHEMA_ID, ContractError, ViewError
from part5rules import COORDINATE_FRAME, part5_input_rules

CLEAN = {"env": {}, "config": False}


@pytest.fixture(scope="module")
def skeleton(real_doc):
    return cli.process(real_doc, **CLEAN)


# --- the registry ---------------------------------------------------------------------------------------------

def test_the_registry_loads_lazily_and_holds_the_built_in_views():
    assert "native" in views.REGISTRY and "part5" in views.REGISTRY
    for name, module in views.REGISTRY.items():
        assert module.NAME == name and module.DESCRIPTION and module.SCHEMA.endswith(".schema.json")
        assert callable(module.render)
    assert views.REGISTRY["native"].SCHEMA == "skeleton.schema.json"
    assert views.REGISTRY["part5"].SCHEMA == "animation-part5.schema.json"


def test_ac_v04_an_unknown_view_names_the_option_and_the_choices(skeleton):
    for view in ("bogus", "", None, 3):
        with pytest.raises(ContractError) as caught:
            views.render(skeleton, view)
        assert str(caught.value) == "--view: must be one of native, part4, part5"


def test_native_returns_the_skeleton_unchanged(skeleton):
    assert views.render(skeleton) is skeleton and views.render(skeleton, "native") == skeleton
    assert views.render(skeleton, "native", keyframes=None, keyframes_person=None) is skeleton


@pytest.mark.parametrize("view", ["native", "part5"])
def test_options_that_only_part4_uses_are_refused_by_the_others(skeleton, view):
    with pytest.raises(ContractError) as caught:
        views.render(skeleton, view, keyframes="every:10")
    assert caught.value.path == "--keyframes" and "--view part4" in str(caught.value)
    with pytest.raises(ContractError) as person:
        views.render(skeleton, view, keyframes_person=3)
    assert person.value.path == "--keyframes-person"


def test_keyframes_doc_is_none_without_a_timeline(skeleton):
    assert views.keyframes_doc(skeleton) is None
    assert views.keyframes_doc(views.render(skeleton, "part5")) is None
    assert views.keyframes_doc("not a document") is None


# --- AC-V05: a new view is one module and one registry entry ---------------------------------------------------

def test_ac_v05_a_dummy_view_registered_in_one_call_renders_and_is_listed(skeleton):
    dummy = types.SimpleNamespace(NAME="dummy", DESCRIPTION="frame numbers only", SCHEMA="dummy.schema.json",
                                  render=lambda sk, **opts: {"frames": [f["frame"] for f in sk["frames"]], **opts})
    views.register(dummy)
    try:
        rendered = views.render(skeleton, "dummy", keyframes="k")
        assert rendered["frames"][:3] == [0, 1, 2] and rendered["keyframes"] == "k"
        with pytest.raises(ContractError) as caught:
            views.render(skeleton, "bogus")
        assert str(caught.value).endswith("native, part4, part5, dummy")
    finally:
        del views.REGISTRY["dummy"]
    assert "dummy" not in views.REGISTRY


# --- AC-V04: the part5 view ---------------------------------------------------------------------------------------

def test_ac_v04_part5_has_the_documented_top_level_shape(skeleton):
    out = views.render(skeleton, "part5")
    assert list(out) == ["format", "producer", "view", "fps", "duration_s", "frame_count", "coordinate_frame", "joints",
                         "bones", "body", "person", "mirror", "source", "frames_skipped", "frames"]
    assert (out["format"], out["producer"], out["view"]) == ("simon.animation.v1", "part3", "part5")
    assert out["coordinate_frame"] == COORDINATE_FRAME and out["joints"] == list(JOINTS)
    assert out["source"] == {"schema": SCHEMA_ID, "sha256": skeleton["input"]["sha256"]}
    assert out["body"] == skeleton["body"] and out["person"] == skeleton["person"]
    assert out["mirror"] == skeleton["mirror"]
    assert out["frame_count"] == len(out["frames"]) == 107 and out["frames_skipped"] == 0
    assert out["duration_s"] == 7.066667 and out["fps"] == 15.0


def test_ac_v04_part5_bones_carry_parent_child_and_length(skeleton):
    bones = views.render(skeleton, "part5")["bones"]
    assert len(bones) == 18
    assert bones[2] == {"name": "left_thigh", "parent": "left_hip", "child": "left_knee",
                        "length_m": skeleton["bone_lengths_m"]["left_thigh"]}
    assert bones[0]["parent"] == "root" and bones[6]["child"] == "neck"


def test_ac_v04_part5_frames_follow_the_animation_shape(skeleton):
    out = views.render(skeleton, "part5")
    first, last = out["frames"][0], out["frames"][-1]
    assert list(first) == ["index", "t", "interpolated", "joints", "conf"]
    assert (first["index"], first["t"], first["interpolated"]) == (0, 0.0, False)
    assert last["index"] == 106 and last["t"] == 7.066667
    assert list(first["joints"]) == list(JOINTS) and len(first["joints"]["nose"]) == 3
    native = skeleton["frames"][5]["people"][0]["joints"]
    assert out["frames"][5]["joints"]["left_knee"] == [native["left_knee"][a] for a in "xyz"]
    assert out["frames"][5]["conf"]["right_ankle"] == native["right_ankle"]["conf"] == 0.3


def test_ac_v04_part5_passes_part5s_documented_input_rules(skeleton, real_doc):
    part5_input_rules(views.render(skeleton, "part5"))
    for kw in ({"body": "part4-rig"}, {"body": "measured"}, {"stature": 1.85}, {"fps": 30}):
        part5_input_rules(views.render(cli.process(real_doc, **CLEAN, **kw), "part5"))


def test_the_rules_checker_itself_rejects_a_native_skeleton_and_bad_part5_files(skeleton):
    with pytest.raises(AssertionError):
        part5_input_rules(skeleton)  # no `format`
    good = views.render(skeleton, "part5")
    for mutate in (lambda d: d["coordinate_frame"].update(y="body_up"),
                   lambda d: d["frames"][3].update(t=0.0),
                   lambda d: d["frames"][3]["joints"].update(nose={"x": 0}),
                   lambda d: d["frames"][3]["joints"]["left_hip"].__setitem__(0, 0.5)):
        broken = copy.deepcopy(good)
        mutate(broken)
        with pytest.raises(AssertionError):
            part5_input_rules(broken)


def test_ac_v04_the_hip_midpoint_is_at_the_origin_in_every_frame(skeleton):
    for frame in views.render(skeleton, "part5")["frames"]:
        for axis in range(3):
            assert abs(frame["joints"]["left_hip"][axis] + frame["joints"]["right_hip"][axis]) < 1e-3


def test_ac_v04_only_frames_holding_the_person_are_written(real_doc):
    gapped = copy.deepcopy(real_doc)
    for k in (0, 1, 50, 51, 106):
        gapped["frames"][k]["people"] = []
    out = views.render(cli.process(gapped, **CLEAN), "part5")
    assert out["frame_count"] == len(out["frames"]) == 102 and out["frames_skipped"] == 5
    assert out["frames"][0]["index"] == 2 and out["frames"][0]["t"] == pytest.approx(0.133333)
    assert 50 not in [f["index"] for f in out["frames"]]
    assert out["duration_s"] == 7.066667  # the whole clip, not only the frames written
    part5_input_rules(out)


def test_ac_v04_a_resampled_part5_file_records_fps_and_grid_indices(real_doc):
    out = views.render(cli.process(real_doc, fps=30, **CLEAN), "part5")
    assert out["fps"] == 30 and out["frame_count"] == 213
    assert [f["index"] for f in out["frames"][:3]] == [0, 1, 2]
    assert out["frames"][1]["t"] == 0.033333
    part5_input_rules(out)


# --- AC-V06: the part5 view always writes fps (Part 6 requires it) ---------------------------------------------

def _clock(t_ms, people=True):
    return {"frames": [{"frame": i, "t_ms": t, "people": [{}] if people else []} for i, t in enumerate(t_ms)]}


def test_ac_v06_fps_is_the_input_clock_rate_on_a_uniform_clock(skeleton):
    assert part5.output_fps(skeleton) == 15.0
    assert part5.output_fps(_clock([0, 33.333, 66.667, 100.0])) == 30.0
    assert part5.output_fps(_clock([0, 1000 / 29.97, 2000 / 29.97])) == 29.97


def test_ac_v06_a_resampled_clip_writes_the_resample_rate():
    doc = _clock([0, 10, 20])
    doc["resample"] = {"fps": 24}
    assert part5.output_fps(doc) == 24


def test_ac_v06_a_non_uniform_clock_writes_the_median_step_rate():
    # steps 40, 50, 50, 200 ms: the median step is 50 ms, so 20 fps; a dropped frame does not move it
    assert part5.output_fps(_clock([0, 40, 90, 140, 340])) == 20.0
    # an even count of steps takes the mean of the two middle steps: 40 and 60 ms give 50 ms
    assert part5.output_fps(_clock([0, 40, 100])) == 20.0


def test_ac_v06_frames_without_the_person_still_set_the_clock():
    doc = _clock([0, 100, 200, 300])
    doc["frames"][1]["people"] = doc["frames"][2]["people"] = []
    assert part5.output_fps(doc) == 10.0


def test_ac_v06_a_clip_with_no_positive_step_writes_30():
    assert part5.output_fps(_clock([0])) == part5.FALLBACK_FPS == 30
    assert part5.output_fps(_clock([5, 5])) == 30


def test_ac_v06_a_very_slow_clock_stays_above_zero():
    rate = part5.output_fps(_clock([0, 10_000_000]))
    assert 0 < rate == 0.0001


def test_ac_v06_every_rendered_part5_file_carries_fps_above_zero(real_doc):
    for kw in ({}, {"fps": 30}, {"body": "part4-rig"}):
        out = views.render(cli.process(real_doc, **CLEAN, **kw), "part5")
        assert isinstance(out["fps"], (int, float)) and out["fps"] > 0


def test_ac_v06_the_schema_requires_fps(skeleton):
    schema = contract.SCHEMAS["animation-part5"]["schema"]
    out = views.render(skeleton, "part5")
    assert jsonschema_lite.validate(out, schema) == []
    missing = {k: v for k, v in out.items() if k != "fps"}
    assert jsonschema_lite.validate(missing, schema)
    assert jsonschema_lite.validate({**out, "fps": 0}, schema)


def test_ac_v06_committed_part5_goldens_and_followers_carry_fps():
    kit = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "conformance"
    files = [kit / "golden" / "view-part5" / "skeleton.json", *sorted((kit / "followers").glob("*/skeleton.json"))]
    assert len(files) == 16
    for path in files:
        doc = json.loads(path.read_text())
        assert doc["format"] == "simon.animation.v1" and doc["fps"] == 15.0, path


def test_ac_v04_times_that_do_not_increase_are_refused_as_part5_would(real_doc):
    bad = copy.deepcopy(real_doc)
    bad["frames"][6]["t_ms"] = bad["frames"][5]["t_ms"]
    with pytest.raises(ViewError) as caught:
        views.render(cli.process(bad, **CLEAN), "part5")
    assert caught.value.path == "--view part5" and "strictly increase" in str(caught.value)
    assert str(caught.value).startswith("--view part5: frame 6: times must strictly increase (Part 5 rejects")
    assert caught.value.page_text.startswith("This clip cannot be written as a Part 5 animation: frame 6: times must")
    assert "--" not in caught.value.page_text


def test_views_do_not_modify_the_skeleton(skeleton):
    before = copy.deepcopy(skeleton)
    views.render(skeleton, "part5")
    views.render(skeleton, "native")
    assert skeleton == before


def test_part5_output_is_deterministic_json(skeleton):
    from part3 import io

    assert io.dumps(views.render(skeleton, "part5")) == io.dumps(views.render(skeleton, "part5"))


# --- review B1: the frame cap goes through views.render ------------------------------------------------------------

@pytest.mark.parametrize("view", ["native", "part5"])
def test_b1_max_frames_is_a_limit_not_an_option_so_native_and_part5_accept_and_ignore_it(skeleton, view):
    assert views.render(skeleton, view, max_frames=20_000) == views.render(skeleton, view)
    assert views.render(skeleton, view, max_frames=None) == views.render(skeleton, view)


def test_b1_part4_takes_max_frames_and_names_the_timeline_when_it_is_too_long(skeleton):
    assert len(views.render(skeleton, "part4", keyframes="every:50", max_frames=213)["keyframes"]) == 6
    with pytest.raises(ContractError) as caught:
        views.render(skeleton, "part4", keyframes="every:50", max_frames=212)
    assert str(caught.value) == "--keyframes: the 30 fps timeline would have 213 ticks; the limit is 212"
    assert views.render(skeleton, "part4", keyframes="every:50", max_frames=None)["timeline"]["frame_count"] == 213


def test_b1_an_option_other_than_a_limit_is_still_refused(skeleton):
    with pytest.raises(ContractError, match="--keyframes: only applies to --view part4"):
        views.render(skeleton, "native", keyframes="every:10", max_frames=20_000)


# --- review B5 and residual 9: one coordinate frame, no skip for built-in views -------------------------------------

def test_b5_both_views_write_the_coordinate_frame_defined_once_in_joints(skeleton):
    from part3 import joints
    part5 = views.render(skeleton, "part5")
    part4 = views.render(skeleton, "part4", keyframes="every:50")
    assert part5["coordinate_frame"] == part4["coordinate_frame"] == joints.COORDINATE_FRAME == COORDINATE_FRAME
    assert part5["coordinate_frame"] is not joints.COORDINATE_FRAME  # a copy: no caller can change the shared one
    for name in ("part4", "part5"):
        assert views.REGISTRY[name].COORDINATE_FRAME is joints.COORDINATE_FRAME  # imported, not copied


def test_r9_a_built_in_view_that_cannot_be_imported_is_an_error_not_a_missing_view(monkeypatch):
    import importlib
    real = importlib.import_module

    def broken(name, *args):
        if name == "part3.views.part5":
            raise ModuleNotFoundError("No module named 'part3.views.part5'", name=name)
        return real(name, *args)

    monkeypatch.setattr(views, "_loaded", None)
    monkeypatch.setattr(views.importlib, "import_module", broken)
    with pytest.raises(ModuleNotFoundError):
        views.names()
