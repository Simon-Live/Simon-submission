"""`python3 -m part3 doctor`: kinds, validation, consumer verdicts (AC-C04, AC-C05). Part 4's rules (AC-C06) are in
test_doctor_part4.py."""

import json

import pytest

import contractkit
from conftest import ROOT
from doctorkit import check, cli
from part3 import adapters, contract, doctor

KIT_INPUTS = ROOT / "fixtures" / "conformance" / "inputs"
KIND_OF_SCHEMA = {
    "pose3d": "pose3d", "keyframes-part1": "keyframes-part1", "keyframes-part4": "keyframes-part4",
    "body-profile": "body-profile", "skeleton": "native", "skeleton-part4": "part4-view",
    "animation-part5": "animation", "people-index": "people-index", "follower-labels": "follower-labels",
}


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
