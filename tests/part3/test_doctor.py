"""`python3 -m part3 doctor`: kinds, validation, consumer verdicts (AC-C04, AC-C05, AC-C06)."""

import copy
import json
import subprocess
import sys
import warnings

import pytest

import contractkit
from conftest import ROOT
from part3 import adapters, contract, doctor, rig

KIT_INPUTS = ROOT / "fixtures" / "conformance" / "inputs"
KIND_OF_SCHEMA = {
    "pose3d": "pose3d", "keyframes-part1": "keyframes-part1", "keyframes-part4": "keyframes-part4",
    "body-profile": "body-profile", "skeleton": "native", "skeleton-part4": "part4-view",
    "animation-part5": "animation", "people-index": "people-index", "follower-labels": "follower-labels",
}


@pytest.fixture
def check(tmp_path, capsys):
    """check(doc, *args) -> (exit code, stdout, stderr) of `doctor.main` on a file holding `doc`.

    A part4 view or a Part 4 authored file gets the keyframes.json Part 4 reads beside it; `beside=False` omits it.
    """
    def run(doc, *args, name="file.json", beside=True):
        path = tmp_path / name
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
        if beside and isinstance(doc, dict) and doc.get("format") == "simon.skeleton.v1":
            (tmp_path / "keyframes.json").write_text(json.dumps(contractkit.keyframes_beside(doc)))
        code = doctor.main([str(path), *args])
        out = capsys.readouterr()
        return code, out.out, out.err
    return run


def cli(*args):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)


# --- AC-C04: each kind is named and accepted ---------------------------------------------------

@pytest.mark.parametrize("name", sorted(KIND_OF_SCHEMA))
def test_each_kind_is_named_with_its_version_and_exits_0(name, check):
    code, out, err = check(contractkit.every_kind()[name])
    assert code == 0, out + err
    assert f"kind: {KIND_OF_SCHEMA[name]} (" in out
    assert f"version {contract.SCHEMAS[name]['version']}" in out
    assert "valid: yes" in out and "Traceback" not in out + err


def test_part4_animation_shaped_like_part4s_own_is_a_valid_animation(check):
    clip = contractkit.part5_view()
    del clip["producer"], clip["view"], clip["source"], clip["person"], clip["mirror"]
    clip.update(fps=30, set="exercise", movement="squat")
    clip["bones"] = [{"name": "spine", "parent": "hip_mid", "child": "shoulder_mid", "length_m": 0.4896}]
    for i, frame in enumerate(clip["frames"]):
        frame["interpolated"] = bool(i % 2)
        del frame["conf"]
    code, out, _ = check(clip, "--for", "part5")
    assert code == 0 and "kind: animation" in out and "Part 5 accepts" in out


def test_native_golden_files_are_accepted(check):
    for path in sorted((ROOT / "fixtures" / "output").rglob("skeleton.json")):
        code, out, _ = check(path.read_text(), name="g.json")
        assert code == 0 and "kind: native" in out, path


@pytest.mark.parametrize("make", [contractkit.as_arrays, contractkit.as_list17, contractkit.as_flat,
                                  contractkit.with_extra_joint, lambda d: contractkit.without(d, "frame")])
def test_tolerated_pose3d_forms_are_accepted_and_named(make, check):
    doc = make(contractkit.pose3d_head())
    code, out, _ = check(doc)
    assert code == 0 and "kind: pose3d" in out and "valid: yes" in out
    assert "tolerated form: adapter " in out


def forms_of(doc):
    """The adapter names `diagnose` puts in its tolerated-form notes for `doc`, in order (the one place doctor names them)."""
    prefix = "tolerated form: adapter "
    return [note[len(prefix):].split(":")[0] for note in doctor.diagnose(doc).notes if note.startswith(prefix)]


def test_each_tolerated_form_names_its_adapter():
    head = contractkit.pose3d_head()
    assert forms_of(head) == []
    cases = {"joint-arrays": contractkit.as_arrays(head), "extra-joints": contractkit.with_extra_joint(head),
             "flat-joints": contractkit.as_flat(head), "frame-index": contractkit.without(head, "frame"),
             "derive-t_ms": contractkit.without(head, "t_ms")}
    for adapter, doc in cases.items():
        assert adapter in forms_of(doc), adapter
    assert forms_of(contractkit.as_list17(head)) == ["joint-arrays"]
    assert forms_of(contractkit.as_flat(head)) == ["flat-joints"]
    assert forms_of({"frames": [1, "x", {"people": "no"}]}) == ["frame-index", "derive-t_ms"]
    assert forms_of({"frames": [1, "x"]}) == []
    assert forms_of({"frames": "no"}) == []


def test_tolerated_forms_are_the_adapters_of_the_registry():
    """doctor asks the adapters themselves, so a new registry entry is named without a doctor change."""
    head = contractkit.pose3d_head()
    assert forms_of(contractkit.as_flat(contractkit.as_arrays(head))) == ["flat-joints", "joint-arrays"]
    assert not hasattr(doctor, "tolerated_forms")
    assert [m.NAME for m in adapters.REGISTRY] == ["flat-joints", "joint-arrays", "extra-joints", "frame-index",
                                                    "derive-t_ms"]


@pytest.mark.parametrize("name,adapter", [
    ("pose3d.arrays.json", "joint-arrays"), ("pose3d.joint-list.json", "joint-arrays"),
    ("pose3d.extra-joints.json", "extra-joints"), ("pose3d.flat.json", "flat-joints"),
    ("pose3d.no-t_ms.json", "derive-t_ms")])
def test_conformance_kit_inputs_are_tolerated_forms_and_name_their_adapter(name, adapter, check):
    path = KIT_INPUTS / name
    if not path.exists():
        pytest.skip("the conformance kit is not in this tree")
    code, out, _ = check(path.read_text(), "--for", "part3")
    assert code == 0, out
    assert f"adapter {adapter}" in out and "kind: pose3d" in out


def test_tolerated_forms_run_through_the_real_adapters(check):
    for make in (contractkit.as_arrays, contractkit.as_list17, contractkit.as_flat, contractkit.with_extra_joint):
        code, out, _ = check(make(contractkit.pose3d_head()), "--for", "part3")
        assert code == 0 and "Part 3 accepts" in out and "adapter" in out, out
    code, out, _ = check(contractkit.without(contractkit.pose3d_head(), "t_ms"), "--for", "part3")
    assert code == 1 and "--input-fps" in out


def test_adapter_failure_on_a_tolerated_form_is_reported_as_invalid(check):
    doc = contractkit.as_arrays(contractkit.pose3d_head())
    del doc["frames"][1]["people"][0]["joints"]["left_knee"]
    code, out, _ = check(doc)
    assert code == 2 and "left_knee" in out


def test_two_person_and_extra_keys_are_still_valid(check):
    doc = contractkit.two_person_pose3d()
    doc["producer_note"] = "extra keys are ignored"
    code, out, _ = check(doc)
    assert code == 0 and "valid: yes" in out


# --- AC-C04: broken files exit 2 and name the field --------------------------------------------

def _set(path, value):
    def apply(doc):
        node = doc
        for step in path[:-1]:
            node = node[step]
        if value is _DELETE:
            node.pop(path[-1])
        else:
            node[path[-1]] = value
    return apply


_DELETE = object()
BROKEN = {
    "pose3d": (_set(("frames", 2, "people", 0, "joints", "left_knee", "conf"), 1.2),
               "pose3d.frames[2].people[0].joints.left_knee.conf"),
    "native": (_set(("input", "sha256"), "abc"), "skeleton.input.sha256"),
    "skeleton-part4": (_set(("keyframes", 1, "local_rotations"), _DELETE),
                       "skeleton.keyframes[1].local_rotations"),
    "animation-part5": (_set(("frames", 0, "joints", "nose"), {"x": 0, "y": 0, "z": 0}),
                        "animation.frames[0].joints.nose"),
    "keyframes-part1": (_set(("people", 0, "repetitions", 0, "keyframes", 1, "t_ms"), _DELETE),
                        "keyframes.people[0].repetitions[0].keyframes[1].t_ms"),
    "keyframes-part4": (_set(("fps",), 25), "keyframes.fps"),
    "body-profile": (_set(("bone_lengths_m", "head"), _DELETE), "profile.bone_lengths_m.head"),
    "people-index": (_set(("people", 0, "file"), _DELETE), "people.people[0]"),
    "follower-labels": (_set(("takes", 1, "faults", 0, "text"), _DELETE), "labels.takes[1].faults[0].text"),
}


@pytest.mark.parametrize("name", sorted(BROKEN))
def test_a_broken_file_exits_2_and_names_the_field(name, check):
    doc = contractkit.every_kind()["skeleton" if name == "native" else name]
    apply, field = BROKEN[name]
    apply(doc)
    code, out, err = check(doc)
    assert code == 2, out
    assert "valid: no" in out and f"error: {field}" in out and "Traceback" not in out + err


def test_part3s_own_validator_adds_what_the_schema_cannot_say(check):
    doc = contractkit.pose3d_head()
    doc["frames"][3]["frame"] = doc["frames"][2]["frame"]
    code, out, _ = check(doc)
    assert code == 2 and "frame indices must be strictly increasing" in out
    native = contractkit.real_skeleton()
    native["person"]["frames_present"] += 1  # a count the schema cannot check
    code, out, _ = check(native)
    assert code == 2 and "error: skeleton.person" in out


def test_body_profile_rules_a_schema_cannot_say(check):
    profile = contractkit.body_profile()
    profile["bone_lengths_m"]["right_pelvis"] = 0.13
    code, out, _ = check(profile)
    assert code == 2 and "profile.bone_lengths_m.right_pelvis: must equal left_pelvis" in out
    profile = contractkit.body_profile()
    profile["bone_lengths_m"]["right_clavicle"] = 0.2
    assert "right_clavicle: must equal left_clavicle" in check(profile)[1]
    profile = contractkit.body_profile()
    profile["stature_m"] = 3.0
    profile["bone_lengths_m"]["head"] = 1.6
    code, out, _ = check(profile)
    assert code == 2 and "profile.stature_m" in out and "profile.bone_lengths_m.head" in out


@pytest.mark.parametrize("doc", [{"hello": 1}, [1, 2], 5, "text", None, {}, {"frames": [1, 2]},
                                 {"format": "simon.part5.labels.v1", "takes": []},
                                 {"schema": "simon.skeleton/2", "frames": []}])
def test_unknown_json_exits_2_with_unknown_kind(doc, check):
    code, out, err = check(json.dumps(doc))
    assert code == 2 and "unknown kind" in out and "Traceback" not in out + err


def test_unknown_kind_names_the_version_it_does_not_read(check):
    out = check({"schema": "simon.skeleton/2", "frames": []})[1]
    assert 'schema "simon.skeleton/2" is not one Part 3 reads' in out and "simon.skeleton/1" in out
    out = check({"format": "simon.part5.labels.v1"})[1]
    assert 'format "simon.part5.labels.v1"' in out


def test_missing_and_non_json_files_exit_2(tmp_path, capsys):
    assert doctor.main([str(tmp_path / "nope.json")]) == 2
    assert "cannot read" in capsys.readouterr().err
    (tmp_path / "bad.json").write_text("{not json")
    assert doctor.main([str(tmp_path / "bad.json")]) == 2
    assert "not valid JSON" in capsys.readouterr().err
    (tmp_path / "binary.json").write_bytes(b"\xff\xfe\x00\x01")
    assert doctor.main([str(tmp_path / "binary.json")]) == 2
    assert "not valid JSON" in capsys.readouterr().err
    (tmp_path / "deep.json").write_text("[" * 200000)
    assert doctor.main([str(tmp_path / "deep.json")]) == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err and "Traceback" not in err
    assert doctor.main([str(tmp_path)]) == 2  # a directory
    assert "cannot read" in capsys.readouterr().err


@pytest.mark.parametrize("doc", [
    {"frames": [{"people": "x"}]}, {"frames": [{"frame": 0, "t_ms": 0, "people": [5]}]},
    {"frames": [{"joints": [1, 2, 3]}]}, {"schema": "simon.skeleton/1"}, {"format": "simon.skeleton.v1"},
    {"format": "simon.animation.v1", "frames": 5}, {"format": "simon.keyframes.v1"},
    {"people": [{"repetitions": 5}]}, {"people": [{"repetitions": []}]}, {"schema": "simon.body_profile/1"},
    {"schema": "simon.part3.people/1", "people": 3}, {"format": "simon.part3.follower_labels/1", "takes": [1]}])
def test_odd_documents_never_produce_a_traceback(doc, check):
    code, out, err = check(json.dumps(doc))
    assert code in (0, 2) and "Traceback" not in out + err


def test_an_unexpected_failure_is_one_plain_line(check, monkeypatch):
    def boom(doc, path=None):
        raise RuntimeError("something odd")
    monkeypatch.setattr(doctor, "diagnose", boom)
    code, out, err = check(contractkit.every_kind()["pose3d"])
    assert code == 2 and "Traceback" not in out + err
    assert err.strip().count("\n") == 0 and "RuntimeError" in err


def test_json_report_parses(check):
    code, out, _ = check(contractkit.every_kind()["skeleton-part4"], "--json", "--for", "part4")
    report = json.loads(out)
    assert code == 0 and report["exit_code"] == 0 and report["valid"] is True
    assert report["kind"] == "part4-view" and report["version"] == "simon.skeleton.v1"
    assert report["consumers"]["part4"] == {"accepts": True, "reason": "", "fix": ""}
    code, out, _ = check({"hello": 1}, "--json")
    assert code == 2 and json.loads(out)["kind"] is None and "unknown kind" in json.loads(out)["errors"][0]


def test_bad_options_exit_2(tmp_path, capsys):
    assert doctor.main([]) == 2
    assert doctor.main([str(tmp_path), "--for", "part9"]) == 2
    assert "usage" in capsys.readouterr().err


def test_runs_standalone_and_through_the_part3_command(tmp_path):
    path = tmp_path / "pose3d.json"
    path.write_text(json.dumps(contractkit.pose3d_head()))
    result = cli("-m", "part3.doctor", str(path), "--for", "part3")
    assert result.returncode == 0 and "kind: pose3d" in result.stdout, result.stderr
    result = cli("-m", "part3", "doctor", str(path))
    if result.returncode == 2 and "invalid choice" in result.stderr:
        pytest.skip("python3 -m part3 doctor is wired by the CLI lane (part3/cli.py)")
    assert result.returncode == 0 and "kind: pose3d" in result.stdout


# --- AC-C05: who would reject, and the fix -----------------------------------------------------

def test_native_skeleton_for_part5_exits_1_with_the_part5_fix(check):
    code, out, _ = check(contractkit.real_skeleton(), "--for", "part5")
    assert code == 1
    assert 'Part 5 would reject: no "format"; fix: python3 -m part3 run ... --view part5' in out


def test_native_skeleton_for_part4_names_the_view_and_keyframes_option(check):
    code, out, _ = check(contractkit.real_skeleton(), "--for", "part4")
    assert code == 1
    assert "Part 4 would reject:" in out and "--view part4 --keyframes" in out


def test_native_skeleton_shows_every_consumer_without_for(check):
    code, out, _ = check(contractkit.real_skeleton())
    assert code == 0
    assert "Part 3 accepts" in out and "Part 4 would reject" in out and "Part 5 would reject" in out


def test_the_fix_doctor_prints_makes_the_file_acceptable(tmp_path, capsys):
    """The five-step path of CONTRACT.md: doctor rejects, the printed option fixes it, doctor accepts."""
    from part3 import cli as pipeline
    source = ROOT / "fixtures" / "input" / "part2-single" / "pose3d.json"
    keys = KIT_INPUTS / "keyframes.part1.json"
    native = tmp_path / "native.json"
    assert pipeline.main(["run", "--in", str(source), "--out", str(native)]) == 0
    assert doctor.main([str(native), "--for", "part5"]) == 1
    assert doctor.main([str(native), "--for", "part4"]) == 1
    capsys.readouterr()
    part5 = tmp_path / "part5.json"  # fix: --view part5
    assert pipeline.main(["run", "--in", str(source), "--out", str(part5), "--view", "part5"]) == 0
    assert doctor.main([str(part5), "--for", "part5"]) == 0
    folder = tmp_path / "p4"  # fix: --view part4 --keyframes <keyframes.json>, with --keyframes-out beside it
    folder.mkdir()
    args = ["run", "--in", str(source), "--out", str(folder / "skeleton.json"), "--view", "part4",
            "--body", "part4-rig", "--keyframes", str(keys), "--keyframes-out", str(folder / "keyframes.json")]
    assert pipeline.main(args) == 0
    capsys.readouterr()
    assert doctor.main([str(folder / "skeleton.json"), "--for", "part4"]) == 0
    out = capsys.readouterr().out
    assert "Part 4 accepts" in out and "not found beside" not in out and "body profile part4-rig" in out
    assert doctor.main([str(folder / "skeleton.json"), "--for", "part5"]) == 0
    assert doctor.main([str(folder / "keyframes.json"), "--for", "part4"]) == 0


def test_pose3d_without_t_ms_names_input_fps(check):
    doc = contractkit.without(contractkit.pose3d_head(), "t_ms")
    code, out, _ = check(doc)
    assert code == 0 and "valid: yes" in out and "adapter derive-t_ms" in out
    code, out, _ = check(doc, "--for", "part3")
    assert code == 1
    assert "Part 3 would reject: pose3d.frames[0].t_ms: missing" in out and "--input-fps <n>" in out


def test_pose3d_without_t_ms_but_with_fps_is_accepted(check):
    doc = contractkit.without(contractkit.pose3d_head(), "t_ms")
    doc["fps"] = 15
    code, out, _ = check(doc, "--for", "part3")
    assert code == 0 and "adapter derive-t_ms fires (t_ms from the top-level fps 15)" in out


def test_two_person_pose3d_names_person_and_all_people(check):
    code, out, _ = check(contractkit.two_person_pose3d(), "--for", "part3")
    assert code == 0
    assert "2 people (ids 0, 1)" in out and "--person <id>" in out and "--all-people" in out


def test_one_person_pose3d_has_no_option_hint(check):
    out = check(contractkit.pose3d_head(), "--for", "part3")[1]
    assert "Part 3 accepts" in out and "--person" not in out


def test_empty_clip_is_rejected_by_part3(check):
    code, out, _ = check({"frames": []}, "--for", "part3")
    assert code == 1 and "pose3d.frames: empty" in out


def test_pose3d_is_not_read_by_part4_or_part5(check):
    doc = contractkit.pose3d_head()
    assert check(doc, "--for", "part4")[0] == 1
    code, out, _ = check(doc, "--for", "part5")
    assert code == 1 and "--view part5" in out


def test_part1_keyframes_need_the_part4_view_option(check):
    doc = contractkit.keyframes_part1()
    code, out, _ = check(doc, "--for", "part4")
    assert code == 1 and "--view part4 --keyframes" in out and "--keyframes-out" in out
    assert check(doc, "--for", "part3")[0] == 0


def test_part4_keyframes_are_read_by_part3_and_part4(check):
    doc = contractkit.keyframes_part4()
    assert check(doc, "--for", "part3")[0] == 0 and check(doc, "--for", "part4")[0] == 0
    doc["frame_count"] = 200  # not round(duration_s * 30) + 1
    code, out, _ = check(doc, "--for", "part4")
    assert code == 1 and "frame_count: 200 does not match duration_s" in out
    doc = contractkit.keyframes_part4(indices=(0, 105, 300))
    code, out, _ = check(doc, "--for", "part4")
    assert code == 1 and "keyframes[2].index: 300 is after the last frame (210)" in out


def test_kinds_nobody_consumes_print_no_consumer_lines(check):
    for name in ("people-index", "follower-labels"):
        out = check(contractkit.every_kind()[name])[1]
        assert "Part 3 accepts" not in out and "would reject" not in out
        code, out, _ = check(contractkit.every_kind()[name], "--for", "part5")
        assert code == 1 and "Part 5 does not read this kind of file" in out


def test_for_on_an_invalid_file_still_exits_2(check):
    assert check({"hello": 1}, "--for", "part5")[0] == 2


def test_follower_labels_accept_format_or_schema(check):
    labels = contractkit.follower_labels()
    assert check(labels)[0] == 0
    labels["schema"] = labels.pop("format")
    assert check(labels)[0] == 0
    del labels["schema"]
    assert check(labels)[0] == 2
    labels = contractkit.follower_labels()
    labels["takes"][1]["faults"][0].pop("measured_in_output")  # added once the output was measured
    assert check(labels)[0] == 0


# --- AC-C05: Part 5's documented rules ---------------------------------------------------------

def test_part3_views_pass_part5s_documented_rules():
    assert doctor.part5_findings(contractkit.part5_view()) == []
    assert doctor.part5_findings(contractkit.part4_view()) == []


PART5_BREAKS = {
    "no format": (lambda d: d.pop("format"), 'no "format"'),
    "unknown format": (lambda d: d.update(format="simon.animation.v2"), 'format "simon.animation.v2" is not'),
    "y is body_up": (lambda d: d["coordinate_frame"].update(y="body_up"), 'coordinate_frame.y: must be "world_up"'),
    "non-canonical joints": (lambda d: d.update(joints=list(reversed(d["joints"]))), "joints: must be the canonical 17"),
    "fps not positive": (lambda d: d.update(fps=0), "fps: must be a positive number"),
    "frames empty": (lambda d: d.update(frames=[]), "frames: must be a non-empty list"),
    "joint as object": (lambda d: d["frames"][1]["joints"].update(nose={"x": 0, "y": 0, "z": 0}),
                        "frames[1].joints.nose: must be [x, y, z] finite numbers, found an object"),
    "joint with 2 numbers": (lambda d: d["frames"][1]["joints"].update(nose=[0, 1]), "frames[1].joints.nose"),
    "t not increasing": (lambda d: d["frames"][3].update(t=d["frames"][2]["t"]),
                         "frames[3].t: times must strictly increase"),
    "t as text": (lambda d: d["frames"][0].update(t="0"), "frames[0].t: must be a number"),
    "conf above 1": (lambda d: d["frames"][0]["conf"].update(nose=1.5), "frames[0].conf.nose"),
    "unknown joint": (lambda d: d["frames"][0]["joints"].update(pelvis=[0, 0, 0]), "frames[0].joints.pelvis: unknown"),
    "hip off by 2 cm": (lambda d: [f["joints"].update(left_hip=[f["joints"]["left_hip"][0], 0.04, 0])
                                   for f in d["frames"]], "hip midpoint must sit at the origin"),
}


@pytest.mark.parametrize("label", sorted(PART5_BREAKS))
def test_part5_rules(label):
    doc = contractkit.part5_view()
    apply, expected = PART5_BREAKS[label]
    apply(doc)
    findings = doctor.part5_findings(doc)
    assert findings and expected in findings[0] + " ".join(findings), (label, findings)


def test_part5_accepts_a_hip_offset_within_1_cm_and_a_missing_t_with_fps():
    doc = contractkit.part5_view()
    for frame in doc["frames"]:
        frame["joints"]["left_hip"][1] += 0.008
        del frame["t"]
    doc["fps"] = 15
    assert doctor.part5_findings(doc) == []
    del doc["fps"]
    assert "needs t (or a top-level fps)" in doctor.part5_findings(doc)[0]


def test_part5_would_reject_part4s_own_object_joints(check):
    """Part 4's authored skeleton.json writes joints as {x, y, z, conf}; Part 5's documented rule wants lists."""
    doc = contractkit.part4_view()
    for key in doc["keyframes"]:
        key["joints"] = {n: {"x": p[0], "y": p[1], "z": p[2], "conf": 1.0} for n, p in key["joints"].items()}
    findings = doctor.part5_findings(doc)
    assert findings and "must be [x, y, z] finite numbers, found an object" in findings[0]


def test_part5_reports_at_most_five_findings():
    doc = contractkit.part5_view()
    for frame in doc["frames"]:
        frame["joints"]["nose"] = "x"
    assert len(doctor.part5_findings(doc)) == doctor.MAX_FINDINGS


def test_animation_failing_part5_blames_the_producer_unless_part3_wrote_it(check):
    clip = contractkit.part5_view()
    clip["coordinate_frame"]["y"] = "body_up"
    code, out, _ = check(clip)  # the schema pins y to world_up, so the file is invalid
    assert code == 2 and "animation.coordinate_frame.y" in out
    clip = contractkit.part5_view()
    for frame in clip["frames"]:
        frame["joints"]["left_hip"][1] += 0.04
    code, out, _ = check(clip, "--for", "part5")
    assert code == 1 and "hip midpoint" in out and "--view part5" in out
    del clip["producer"]
    out = check(clip, "--for", "part5")[1]
    assert "fix the producer of this file" in out


# --- AC-C06: Part 4's rules --------------------------------------------------------------------

def test_a_clean_part4_view_passes_part4s_rules(check):
    code, out, _ = check(contractkit.part4_view(), "--for", "part4")
    assert code == 0 and "Part 4 accepts" in out and "not checked" not in out
    assert "rig.fit" in out and "12.0 mm at nose" in out


def test_key_t_off_by_1_ms_reports_the_part4_rule(check):
    doc = contractkit.part4_view()
    doc["keyframes"][1]["t"] = round(doc["keyframes"][1]["t"] + 0.001, 6)
    code, out, _ = check(doc, "--for", "part4")
    assert code == 1
    assert "Part 4 would reject: keyframes[1].t:" in out and "is not index / 30" in out
    assert "Part 4 allows 1" in out and "--view part4" in out
    assert check(doc)[0] == 0  # valid file, only Part 4 rejects it


def test_key_t_within_1_microsecond_is_accepted(check):
    doc = contractkit.part4_view()
    doc["keyframes"][1]["t"] = round(doc["keyframes"][1]["t"] + 5e-7, 6)
    assert check(doc, "--for", "part4")[0] == 0


def test_fk_residual_over_1_mm_reports_the_part4_rule(check):
    doc = contractkit.part4_view()
    doc["keyframes"][2]["joints"]["left_wrist"][1] += 0.002
    code, out, _ = check(doc, "--for", "part4")
    assert code == 1
    assert "keyframes[2].joints.left_wrist: forward kinematics of local_rotations misses it by 2.0 mm" in out
    doc["keyframes"][2]["joints"]["left_wrist"][1] -= 0.0015  # 0.5 mm off is fine
    assert check(doc, "--for", "part4")[0] == 0


def test_a_rule_doctor_cannot_check_is_a_rejection_not_an_accept(check, monkeypatch):
    """Review B3: forward kinematics that cannot run must not read as 'Part 4 accepts'."""
    def boom(rotations, rest):
        raise ValueError("pelvis rotation is zero")
    monkeypatch.setattr(rig, "forward", boom)
    code, out, _ = check(contractkit.part4_view(), "--for", "part4")
    assert code == 1 and "Part 4 accepts" not in out
    assert ("Part 4 would reject: keyframes[0]: forward kinematics could not be checked (pelvis rotation is zero)"
            in out)


def test_a_quaternion_under_norm_1e_8_is_rejected_like_part4_does(check):
    """Review B3: Part 4 rejects any rotation with a norm under 1e-8, not only an all-zero one."""
    doc = contractkit.part4_view()
    doc["keyframes"][1]["local_rotations"]["left_knee"] = [1e-9, 0, 0, 0]
    code, out, _ = check(doc, "--for", "part4")
    assert code == 1
    assert "Part 4 would reject: keyframes[1].local_rotations.left_knee: norm 1.0e-09 is under 1e-08" in out
    assert "Part 4 accepts" not in out
    leaf = contractkit.with_rotation(contractkit.part4_view(), 1, "left_ankle", [0, 0, 0, 9e-9])
    assert check(leaf, "--for", "part4")[0] == 1
    leaf = contractkit.with_rotation(contractkit.part4_view(), 1, "left_ankle", [0, 0, 0, 2e-8])  # a leaf: no FK effect
    assert check(leaf, "--for", "part4")[0] == 0


def test_real_rig_forward_agrees_with_the_reference(check):
    view = contractkit.part4_view()
    for key in view["keyframes"]:
        fk = rig.forward(key["local_rotations"], view["rest_offsets_m"])
        for name, point in key["joints"].items():
            assert max(abs(a - b) for a, b in zip(fk[name], point)) < 1e-5, name
    code, out, _ = check(view, "--for", "part4")
    assert code == 0 and "not checked" not in out
    view["keyframes"][1]["joints"]["left_wrist"][1] += 0.002
    assert check(view, "--for", "part4")[0] == 1


def test_real_part4_view_output_validates_and_passes_every_consumer(check):
    from part3 import cli as pipeline
    from part3.views import part4 as views
    doc = json.loads((ROOT / "fixtures" / "input" / "part2-single" / "pose3d.json").read_text())
    rendered = views.render(pipeline.process(doc), keyframes="every:10")
    code, out, _ = check(rendered, "--for", "part4")
    assert code == 0 and "kind: part4-view" in out and "Part 4 accepts" in out and "Part 5 accepts" in out
    keys = views.keyframes_doc(rendered)
    assert keys is not None and check(keys, "--for", "part4")[0] == 0


PART4_BREAKS = {
    "joints reversed": (lambda d: d.update(joints=list(reversed(d["joints"]))), "joints: must be the canonical 17"),
    "rest parent changed": (lambda d: d["rest_offsets_m"]["left_knee"].update(parent="pelvis"),
                            'rest_offsets_m.left_knee.parent: must be "left_hip"'),
    "rest joint missing": (lambda d: d["rest_offsets_m"].pop("neck"), "rest_offsets_m.neck: missing"),
    "rest offset short": (lambda d: d["rest_offsets_m"]["neck"].update(offset=[0, 1]),
                          "rest_offsets_m.neck.offset"),
    "fps 25": (lambda d: d["timeline"].update(fps=25), "timeline.fps: must be 30"),
    "frame_count off": (lambda d: d["timeline"].update(frame_count=12), "timeline.frame_count: 12 does not match"),
    "keys repeat": (lambda d: d["keyframes"][2].update(index=10, t=round(10 / 30, 6)),
                    "keyframes[2].index: key indices must strictly increase (10 after 10)"),
    "key after the clip": (lambda d: d["keyframes"][2].update(index=211, t=round(211 / 30, 6)),
                           "keyframes[2].index: 211 is after the last frame (210)"),
    "key before the clip": (lambda d: d["keyframes"][0].update(index=-1, t=0),
                            "keyframes[0].index: -1 is before the first frame"),
    "rotation missing": (lambda d: d["keyframes"][1]["local_rotations"].pop("left_knee"),
                         "keyframes[1].local_rotations.left_knee: missing"),
    "zero quaternion": (lambda d: d["keyframes"][1]["local_rotations"].update(neck=[0, 0, 0, 0]),
                        "keyframes[1].local_rotations.neck: norm 0.0e+00 is under 1e-08"),
    "tiny quaternion": (lambda d: d["keyframes"][1]["local_rotations"].update(neck=[1e-9, 0, 0, 0]),
                        "keyframes[1].local_rotations.neck: norm 1.0e-09 is under 1e-08"),
    "key joints unreadable": (lambda d: d["keyframes"][1]["joints"].pop("nose"),
                              "keyframes[1].joints: must hold the 17 joints as [x, y, z]"),
    "short quaternion": (lambda d: d["keyframes"][1]["local_rotations"].update(neck=[0, 0, 1]),
                         "keyframes[1].local_rotations.neck: must be a quaternion"),
    "no keys": (lambda d: d.update(keyframes=[]), "keyframes: the skeleton has no keyframes"),
    "no format": (lambda d: d.pop("format"), 'no "format"'),
}


@pytest.mark.parametrize("label", sorted(PART4_BREAKS))
def test_part4_rules(label):
    doc = contractkit.part4_view()
    assert doctor.part4_skeleton_findings(doc) == []
    apply, expected = PART4_BREAKS[label]
    apply(doc)
    findings = doctor.part4_skeleton_findings(doc)
    assert findings and expected in " | ".join(findings), (label, findings)


def test_part4_keyframes_file_rules():
    doc = contractkit.keyframes_part4()
    assert doctor.part4_keyframes_findings(doc) == []
    doc["fps"] = 60
    assert doctor.part4_keyframes_findings(doc)[0] == "fps: must be 30, got 60"
    doc = contractkit.keyframes_part4()
    doc["keyframes"][1]["t"] = 3.6
    assert "keyframes[1].t:" in doctor.part4_keyframes_findings(doc)[0]
    doc = contractkit.keyframes_part4()
    doc["keyframes"] = []
    assert doctor.part4_keyframes_findings(doc)[-1] == "keyframes: no keys"


def test_part4_needs_keyframes_json_beside_the_skeleton(check):
    """Review residual 3: Part 4 cannot run without keyframes.json, so its absence is a rejection."""
    code, out, _ = check(contractkit.part4_view(), "--for", "part4", beside=False)
    assert code == 1
    assert ("Part 4 would reject: keyframes.json: not found beside this file "
            "(Part 4 needs keyframes.json beside skeleton.json)") in out
    assert "fix: python3 -m part3 run ... --view part4 --keyframes <keyframes.json> --keyframes-out <dir>/" in out
    assert check(contractkit.part4_view(), "--for", "part4")[0] == 0
    assert check(contractkit.part4_view(), beside=False)[0] == 0  # the file is valid; only Part 4 rejects it


def test_a_document_without_a_path_cannot_have_its_keyframes_json_checked():
    verdict = doctor.diagnose(contractkit.part4_view()).consumers["part4"]
    assert not verdict.accepts and "cannot look for it beside this file (no file path given)" in verdict.reason


def test_keyframes_json_beside_the_skeleton_must_list_the_same_indices(tmp_path, capsys):
    skeleton = tmp_path / "skeleton.json"
    skeleton.write_text(json.dumps(contractkit.part4_view()))
    beside = tmp_path / "keyframes.json"
    beside.write_text(json.dumps(contractkit.keyframes_part4(indices=(0, 10, 20), names=("a", "b", "c"))))
    assert doctor.main([str(skeleton), "--for", "part4"]) == 0
    assert "not found" not in capsys.readouterr().out
    beside.write_text(json.dumps(contractkit.keyframes_part4(indices=(0, 10, 30), names=("a", "b", "c"))))
    code = doctor.main([str(skeleton), "--for", "part4"])
    out = capsys.readouterr().out
    assert code == 1
    assert ("keyframes.json: key indices differ at key 2: it lists 30, this file has 20 "
            "(it lists 3 keys, this file has 3)") in out
    beside.write_text("not json")
    assert doctor.main([str(skeleton), "--for", "part4"]) == 1
    assert "not a readable simon.keyframes.v1 list" in capsys.readouterr().out


@pytest.mark.parametrize("indices,names,expected", [
    ((0, 10), ("a", "b"), "differ at key 2: it lists none (it lists 2 keys, this file has 3)"),
    ((0, 10, 20, 30), ("a", "b", "c", "d"), "differ at key 3: this file has none (it lists 4 keys, this file has 3)"),
    ((5, 10, 20), ("a", "b", "c"), "differ at key 0: it lists 5, this file has 0 (it lists 3 keys, this file has 3)")])
def test_an_index_mismatch_names_the_first_difference_and_both_lengths(indices, names, expected, tmp_path, capsys):
    skeleton = tmp_path / "skeleton.json"
    skeleton.write_text(json.dumps(contractkit.part4_view()))
    (tmp_path / "keyframes.json").write_text(json.dumps(contractkit.keyframes_part4(indices=indices, names=names)))
    assert doctor.main([str(skeleton), "--for", "part4"]) == 1
    assert expected in capsys.readouterr().out


def test_the_part4_view_notes_the_rig_residual_it_reports(check):
    doc = contractkit.part4_view()
    out = check(doc)[1]
    assert "note: rig.fit: key poses were snapped to Part 4's rig; worst residual 12.0 mm at nose (key 20)" in out
    del doc["rig"]["fit"]
    assert check(doc)[0] == 2  # rig.fit is part of the contract


def test_every_message_is_one_plain_line(check):
    for name, doc in contractkit.every_kind().items():
        code, out, err = check(doc, "--for", "part5")
        assert code in (0, 1), name
        assert "Traceback" not in out + err
        assert all(line.strip() for line in out.splitlines()), name


def test_consumer_report_is_a_dict_of_named_verdicts():
    report = doctor.diagnose(contractkit.real_skeleton(), "x.json")
    assert set(report.consumers) == {"part3", "part4", "part5"}
    accepts, reason, fix = report.consumers["part5"]
    assert accepts is False and reason == 'no "format"' and fix == "python3 -m part3 run ... --view part5"
    assert report.path == "x.json" and report.kind == "native" and report.version == "simon.skeleton/1"
    assert copy.deepcopy(report.to_dict())["consumers"]["part3"]["accepts"] is True


# --- review B2: Part 4's long-way rule ---------------------------------------------------------

def _shoulder_flip():
    """Keys 10 and 20 turn the left shoulder 170 degrees about +z and then 170 degrees about -z: 340 apart."""
    view = contractkit.with_rotation(contractkit.part4_view(), 1, "left_shoulder",
                                     contractkit.axis_angle([0, 0, 1], 170))
    return contractkit.with_rotation(view, 2, "left_shoulder", contractkit.axis_angle([0, 0, 1], -170))


def test_a_shoulder_that_flips_through_180_degrees_between_keys_is_rejected_naming_joint_and_keys(check):
    code, out, _ = check(_shoulder_flip(), "--for", "part4")
    assert code == 1
    assert "Part 4 would reject: left_shoulder turns 340.0 degrees between keys 10 and 20 (Part 4 allows 180)" in out
    assert "fix: add keys between them (a smaller every:<n> or more keys in the keyframes file) or use another" in out
    assert "Part 4 accepts" not in out
    assert check(_shoulder_flip())[0] == 0  # the file is valid; only Part 4 rejects it
    assert check(contractkit.part4_view(), "--for", "part4")[0] == 0


def test_the_long_way_rule_reads_the_quaternion_not_its_sign(check):
    """q and -q are the same rotation; Part 4 aligns each key to the previous key's hemisphere before the check."""
    q = contractkit.axis_angle([0, 0, 1], 100)
    view = contractkit.with_rotation(contractkit.part4_view(), 1, "left_shoulder", q)
    view = contractkit.with_rotation(view, 2, "left_shoulder", [-c for c in q])
    assert check(view, "--for", "part4")[0] == 0


# --- review residual 2: simon.skeleton.v1 files Part 3 did not write ----------------------------

def test_part4s_own_skeleton_is_named_and_gets_the_part4_and_part5_verdicts(check):
    code, out, _ = check(contractkit.part4_authored(), "--for", "part4")
    assert code == 0
    assert "kind: part4-other (simon.skeleton.v1 (not written by Part 3)), version simon.skeleton.v1" in out
    assert "valid: yes" in out and "note: not written by Part 3" in out
    assert json.loads(check(contractkit.part4_authored(), "--json")[1])["kind"] == "part4-other"
    assert "Part 4 accepts" in out
    assert "Part 5 would reject: keyframes[0].joints.nose: must be [x, y, z] finite numbers, found an object" in out
    assert "Part 3 accepts" not in out and "Part 3 would reject" not in out


def test_part4s_own_skeleton_gets_part4s_rules_applied(check):
    doc = contractkit.part4_authored()
    doc["keyframes"][2]["joints"]["left_wrist"]["y"] += 0.01
    code, out, _ = check(doc, "--for", "part4")
    assert code == 1 and "keyframes[2].joints.left_wrist: forward kinematics of local_rotations misses it" in out
    assert check(doc)[0] == 0  # a known kind, valid; only Part 4 rejects it
    doc = contractkit.part4_authored()
    del doc["keyframes"][1]["joints"]["nose"]
    code, out, _ = check(doc, "--for", "part4")
    assert code == 1 and "keyframes[1].joints: must hold the 17 joints as [x, y, z]" in out
    doc = contractkit.part4_authored()
    del doc["keyframes"]
    code, out, _ = check(doc)
    assert code == 2 and "error: keyframes: must be a list of key poses" in out


def test_part4s_own_skeleton_gets_the_beside_and_long_way_rules_too(check):
    code, out, _ = check(contractkit.part4_authored(), "--for", "part4", beside=False)
    assert code == 1 and "keyframes.json: not found beside this file" in out and "Part 4 accepts" not in out
    code, out, _ = check(contractkit.part4_authored(_shoulder_flip()), "--for", "part4")
    assert code == 1 and "left_shoulder turns 340.0 degrees between keys 10 and 20" in out


def part4_fix(check, doc, **options):
    """The fix line of the Part 4 verdict, from the JSON report."""
    return json.loads(check(doc, "--json", **options)[1])["consumers"]["part4"]["fix"]


def test_r4_a_foreign_part4_file_gets_the_producer_fix_for_every_part4_finding(check):
    code, out, _ = check(contractkit.part4_authored(), "--for", "part4", beside=False)  # no keyframes.json beside it
    line = next(l for l in out.splitlines() if l.startswith("Part 4 would reject"))
    assert code == 1 and line.endswith(f"; fix: {doctor.FIX_PRODUCER}") and "keyframes.json: not found" in line
    broken_fk = contractkit.part4_authored()
    broken_fk["keyframes"][2]["joints"]["left_wrist"]["y"] += 0.01
    for doc in (contractkit.part4_authored(_shoulder_flip()), broken_fk):  # the long way; forward kinematics
        assert part4_fix(check, doc) == doctor.FIX_PRODUCER


def test_r4_a_part3_file_keeps_its_own_part4_fixes(check):
    assert part4_fix(check, contractkit.part4_view(), beside=False) == doctor.FIX_KEYFRAMES_OUT
    assert part4_fix(check, _shoulder_flip()) == doctor.FIX_LONG_WAY


def test_a_part3_file_with_a_broken_native_block_is_not_taken_for_a_foreign_one(check):
    doc = contractkit.part4_view()
    del doc["input"]["sha256"]
    code, out, _ = check(doc, "--for", "part4")
    assert code == 2 and "kind: part4-view" in out and "not written by Part 3" not in out


# --- review residual 5: per-frame bone lengths ---------------------------------------------------

def test_a_native_frame_with_a_bone_over_2_percent_off_is_invalid_and_names_frame_and_bone(check):
    doc = contractkit.real_skeleton()
    first = next(i for i, f in enumerate(doc["frames"]) if f["people"])
    knee = doc["frames"][first]["people"][0]["joints"]["left_knee"]
    knee["y"] = round(knee["y"] + 0.003, 6)  # 0.3 cm: under 2% of the thigh or the shank
    assert check(doc)[0] == 0
    knee["y"] = round(knee["y"] + 0.05, 6)  # 5 cm
    code, out, _ = check(doc)
    assert code == 2 and "valid: no" in out
    assert f"error: skeleton.frames[{first}].people[0]: bone left_" in out and "than bone_lengths_m" in out
    assert "the limit is 2%" in out


def test_a_part4_key_with_a_bone_over_2_percent_off_is_invalid(check):
    doc = contractkit.part4_view()
    doc["keyframes"][1]["joints"]["left_knee"][1] += 0.05
    code, out, _ = check(doc, "--for", "part4")
    assert code == 2 and "error: skeleton.keyframes[1].joints: bone left_" in out and "than bone_lengths_m" in out


def test_part3s_own_goldens_keep_their_bone_lengths(check):
    for name in ("view-part4-every-10", "profile-part4-rig", "profile-stature-185", "fps-30"):
        path = ROOT / "fixtures" / "conformance" / "golden" / name / "skeleton.json"
        if path.exists():
            assert check(path.read_text(), name="skeleton.json")[0] == 0, name


# --- review round 2, R12: a quaternion near the float limit is a rejection, not a warning -------------------------

HUGE_QUATERNIONS = [[1e308, 1e308, 0, 0], [1e308] * 4, [-1e308, 1e308, 1e308, -1e308]]


def with_huge_rotation(q):
    doc = contractkit.part4_view()
    doc["keyframes"][1]["local_rotations"]["left_shoulder"] = q
    return doc


@pytest.mark.parametrize("q", HUGE_QUATERNIONS)
def test_r12_a_huge_quaternion_is_rejected_by_part4_and_raises_no_warning(q, check):
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a numpy overflow warning would become an exception, then a stderr line
        code, out, err = check(with_huge_rotation(q), "--for", "part4")
    assert err == "" and "could not check" not in out
    assert code == 1 and "Part 4 would reject: keyframes[1].joints." in out and "forward kinematics" in out


@pytest.mark.parametrize("q", HUGE_QUATERNIONS)
def test_r12_a_huge_quaternion_in_part4s_own_file_is_rejected_too(q):
    doc = contractkit.part4_authored(with_huge_rotation(q))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        report = doctor.diagnose(doc)
    assert report.valid and report.consumers["part4"].accepts is False


def test_r12_the_command_line_prints_nothing_on_stderr_for_a_huge_quaternion(tmp_path):
    path = tmp_path / "skeleton.json"
    doc = with_huge_rotation([1e308, 1e308, 0, 0])
    path.write_text(json.dumps(doc))
    (tmp_path / "keyframes.json").write_text(json.dumps(contractkit.keyframes_beside(doc)))
    result = cli("-W", "default", "-m", "part3", "doctor", str(path), "--for", "part4")
    assert result.returncode == 1 and result.stderr == "", result.stderr
    assert "Part 4 would reject" in result.stdout
