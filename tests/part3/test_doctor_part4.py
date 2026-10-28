"""`python3 -m part3 doctor` on Part 4's side: Part 4's rules, the long-way rule, files Part 3 did not write and
per-frame bone lengths (AC-C06, review B2, residuals 2 and 5, round 2 R12). The kinds, broken files and the Part 5
verdicts are in test_doctor.py."""

import copy
import json
import warnings

import pytest

import contractkit
from conftest import ROOT
from doctorkit import check, cli
from part3 import doctor, rig

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
    assert f"fix: {rig.LONG_WAY_FIX}" in out
    assert "fix: add keys between them (a smaller every:<n>) or use another view" in out
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
