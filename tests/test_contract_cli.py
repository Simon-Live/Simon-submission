"""The integration contract (docs/specs/integration-contract.md): the seven published schemas, the
compatibility table, `part5 contract` and `make check-5-contract` (AC-C01 to AC-C04, AC-C12, AC-C-NFR-01), and
the J1 additions (docs/specs/journey-followup.md AC-C02, AC-C03: the replay schema and row, the goldens).
AC-C10 (plain errors from `make contracts-check`) is covered by tests/test_sync_contracts.py."""
import copy
import json
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from part5 import cli, contract
from part5.io import JOINTS, parse_clip
from part5.output import GENERIC_MEASURES, OutputError, SIDES, _joint_for, _spec, validate_analysis

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "fixtures/output/analysis.example.json"
CORRECT = ROOT / "fixtures/output/analysis.no-faults.example.json"
BASE = "https://github.com/moalborati/simon-part-5-fault-analysis/contracts/"


def validator(name):
    return contract.make_validator(name)


def errors(name, doc):
    return contract.schema_errors(validator(name), doc)


@pytest.fixture(scope="module")
def summary():
    return contract.check(ROOT)


# ---------------------------------------------------------------- AC-C01
@pytest.mark.parametrize("name,version", [("analysis", "1.7.0"), ("input-animation", "1.0.0"),
                                          ("input-skeleton", "1.0.0"), ("labels", "1.0.0"),
                                          ("metrics", "1.3.0"), ("replay", "1.0.0"), ("input-feet", "1.0.0")])
def test_ac_c01_schema_is_published_with_id_and_version(name, version):
    schema = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text())
    assert schema["$id"] == f"{BASE}{name}.schema.json"
    assert schema["version"] == version
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(schema)


def test_ac_c01_check_lists_the_six_schemas_and_the_copies_as_valid(summary):
    by_name = {s["name"]: s for s in summary["schemas"]}
    assert set(contract.SCHEMA_NAMES) <= set(by_name)
    assert {"part3/skeleton", "part3/animation-part5", "part4/animation"} <= set(by_name)
    assert all(s["valid"] for s in summary["schemas"])


# ---------------------------------------------------------------- AC-C02, AC-C03
def test_ac_c02_every_committed_fixture_validates_and_loads(summary):
    assert summary["failures"] == []
    by = summary["validated"]["by_schema"]
    assert by["input-animation"] >= 100  # 96 follower takes, 2 expected clips, the kit and Part 4's clip
    assert by["part3/animation-part5"] >= 16 and by["part4/animation"] == 1
    assert by["part3/skeleton"] == 1 and by["part3/skeleton-part4"] == 1 and by["input-skeleton"] == 1
    assert by["labels"] >= 1 and by["part3/follower-labels"] == 1 and by["analysis"] >= 2
    assert 100 <= summary["validated"]["files"] <= sum(by.values())  # some files meet two schemas
    assert summary["validated"]["loaded_through_part5"] >= 100
    assert summary["validated"]["rejected_as_documented"] == 1  # Part 3's native view


def test_ac_c03_golden_outputs_rebuild_byte_for_byte(summary):
    goldens = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "fixtures/output").glob("*.json"))
    assert len(goldens) == 3 and summary["rebuilt_identical"] == goldens
    assert "fixtures/output/replay.example.json" in goldens


def test_ac_c03_the_golden_replay_is_validated_and_its_lengths_checked(summary):
    assert summary["validated"]["by_schema"]["replay"] == 1 and summary["validated"]["replays_checked"] == 1


# ---------------------------------------------------------------- a corrupted copy makes the check exit 1
@pytest.fixture(scope="module")
def mini_root(tmp_path_factory):
    """The contract, the small fixture sets and the goldens: enough for `--check`, quick to copy."""
    root = tmp_path_factory.mktemp("mini")
    shutil.copytree(ROOT / "contracts", root / "contracts")
    shutil.copytree(ROOT / "fixtures/input/contract", root / "fixtures/input/contract")
    shutil.copytree(ROOT / "fixtures/output", root / "fixtures/output")
    shutil.copytree(ROOT / "fixtures/input/expected/exercise", root / "fixtures/input/expected/exercise")
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    for take in labels["takes"]:
        if take["take_id"].startswith(("exercise_front_good_08", "exercise_front_good_00")):
            dst = root / take["follower"]
            dst.parent.mkdir(parents=True)
            shutil.copy(ROOT / take["follower"], dst)
    shutil.copy(ROOT / "fixtures/input/followers/labels.json", root / "fixtures/input/followers/labels.json")
    return root


def run_check(root):
    return subprocess.run([sys.executable, "-m", "part5.contract", "--check", "--root", str(root)],
                          capture_output=True, text=True, cwd=ROOT)


def test_a_clean_copy_passes_through_the_module_entry_point(mini_root):
    out = run_check(mini_root)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["failures"] == []
    assert out.stderr.strip() == "check-5-contract: PASS"


def corrupt_follower(root):
    p = root / "fixtures/input/contract/part3/followers/squat_front_correct/skeleton.json"
    doc = json.loads(p.read_text())
    del doc["frames"][3]["joints"]["left_knee"]
    doc["frames"][4]["joints"]["nose"] = [0.1, 0.2]
    p.write_text(json.dumps(doc))


def break_copied_schema(root):
    p = root / "contracts/part3/animation-part5.schema.json"
    doc = json.loads(p.read_text())
    doc["type"] = 5
    p.write_text(json.dumps(doc))


def shift_golden(root):
    p = root / "fixtures/output/analysis.example.json"
    doc = json.loads(p.read_text())
    doc["faults"][0]["magnitude_deg"] += 0.1
    p.write_text(json.dumps(doc, indent=2) + "\n")


def shorten_replay_map(root):
    p = root / "fixtures/output/replay.example.json"
    doc = json.loads(p.read_text())
    doc["exp_to_fol"] = doc["exp_to_fol"][:-1]
    p.write_text(json.dumps(doc))


def shift_replay_time(root):
    p = root / "fixtures/output/replay.example.json"
    doc = json.loads(p.read_text())
    doc["follower_t"][5] += 0.001
    p.write_text(json.dumps(doc, allow_nan=False) + "\n")


def accept_native(root):
    p = root / "fixtures/input/contract/part3/native/skeleton.json"
    doc = json.loads(p.read_text())
    doc["format"] = "simon.animation.v1"
    p.write_text(json.dumps(doc))


@pytest.mark.parametrize("corrupt,expect", [
    (corrupt_follower, "part3/followers/squat_front_correct/skeleton.json"),
    (break_copied_schema, "part3/animation-part5.schema.json"),
    (shift_golden, "analysis.example.json"),
    (shorten_replay_map, "replay.example.json: exp_to_fol: has 90 entries but expected has 91 frames"),
    (shift_replay_time, "replay.example.json: rebuilt through the pipeline it differs"),
    (accept_native, "native/skeleton.json"),
])
def test_a_corrupted_copy_makes_check_5_contract_exit_1(mini_root, tmp_path, corrupt, expect):
    root = tmp_path / "root"
    shutil.copytree(mini_root, root)
    corrupt(root)
    out = run_check(root)
    assert out.returncode == 1
    failures = json.loads(out.stdout)["failures"]
    assert failures and any(expect in f for f in failures)
    assert "check-5-contract: FAIL" in out.stderr


def test_a_missing_required_fixture_directory_fails(mini_root, tmp_path):
    root = tmp_path / "root"
    shutil.copytree(mini_root, root)
    shutil.rmtree(root / "fixtures/input/expected")
    assert any("fixtures/input/expected: directory is missing" in f for f in contract.check(root)["failures"])


def test_a_fixture_no_schema_covers_is_a_failure(mini_root, tmp_path):
    root = tmp_path / "root"
    shutil.copytree(mini_root, root)
    (root / "fixtures/output/mystery.json").write_text('{"format": "simon.unknown.v9"}')
    assert any("mystery.json: no schema covers this file" in f for f in contract.check(root)["failures"])


def test_check_5_contract_needs_the_flag():
    result = subprocess.run([sys.executable, "-m", "part5.contract"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 2 and "--check" in result.stderr


def test_check_without_jsonschema_says_so_and_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(contract, "have_jsonschema", lambda: False)
    assert contract.main(["--check"]) == 2
    assert "needs the jsonschema package" in capsys.readouterr().err


# ---------------------------------------------------------------- AC-C04, AC-C12
def test_ac_c04_contract_prints_the_table_with_every_row(capsys):
    assert cli.main(["contract"]) == 0
    out = capsys.readouterr().out
    for row in contract.table_rows():
        assert row["producer"] in out and row["file"] in out
    for name in contract.SCHEMA_NAMES:
        assert f"contracts/{name}.schema.json" in out


@pytest.mark.parametrize("name", contract.SCHEMA_NAMES)
def test_ac_c04_schema_flag_prints_the_file_byte_for_byte(name):
    result = subprocess.run([sys.executable, "-m", "part5", "contract", "--schema", name],
                            capture_output=True, cwd=ROOT)
    assert result.returncode == 0
    assert result.stdout == (ROOT / "contracts" / f"{name}.schema.json").read_bytes()


def test_ac_c04_json_flag_parses_and_is_the_contract_document(capsys):
    assert cli.main(["contract", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) == {"schemas", "table"} and doc == contract.contract_document()
    assert [s["name"] for s in doc["schemas"]] == list(contract.SCHEMA_NAMES)
    assert doc["schemas"][0]["schema"]["$id"] == doc["schemas"][0]["id"]
    assert len(doc["table"]) == len(contract.TABLE_ROWS)


def test_ac_c04_unknown_schema_exits_2_naming_the_valid_names(capsys):
    assert cli.main(["contract", "--schema", "nope"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("part5 contract: no schema named nope; one of analysis, input-animation")
    assert "metrics" in err


def test_table_rows_name_the_spec_cases():
    pose = next(r for r in contract.table_rows() if r["producer"] == "Part 2")
    assert pose["verdict"] == "rejected" and "run Part 3 --view part5" in pose["fix"]
    handoffs = [r for r in contract.table_rows() if "hand-off" in r["producer"]]
    assert len(handoffs) == 2 and any("simon:follow" in r["file"] for r in handoffs)
    assert all("files.animation" in r["fix"] and "--expected" in r["fix"] for r in handoffs)


def test_commits_come_from_the_lock_file_and_the_neighbour_check():
    lock = json.loads((ROOT / "contracts/sources.lock.json").read_text())["upstreams"]
    rows = contract.table_rows()
    part3 = [r for r in rows if r["checked_against"].startswith("Part 3 ")]
    part4 = [r for r in rows if r["checked_against"].startswith("Part 4 ")]
    assert part3 and all(r["checked_against"] == f"Part 3 {lock['part3']['commit'][:7]}" for r in part3)
    assert part4 and all(r["checked_against"] == f"Part 4 {lock['part4']['commit'][:7]}" for r in part4)
    for part, sha in contract.NEIGHBOUR_COMMITS.items():
        assert re.fullmatch(r"[0-9a-f]{7}", sha), part
        assert any(r["checked_against"] == f"Part {part[-1]} {sha}" for r in rows)


def test_ac_c12_exit_code_mapping_is_in_the_table_and_contract_md():
    row = next(r for r in contract.table_rows() if r["file"] == "`part5 analyse` exit code")
    assert row["verdict"] == "works with a mapping"
    assert "3 is no longer used" in row["format"]
    assert '0 is "written" (read `warnings`)' in row["fix"]
    text = (ROOT / "CONTRACT.md").read_text()
    assert "`analyse` never refuses a take" in text
    assert "Read `warnings` and `score`" in text


def test_contract_md_carries_the_generated_table_and_schema_list():
    text = (ROOT / "CONTRACT.md").read_text()
    block = re.search(r"<!-- part5-compatibility:begin -->\n(.*?)\n<!-- part5-compatibility:end -->", text, re.S)
    assert block and block.group(1).strip() == contract.table_markdown(contract.table_rows())
    for s in contract.schema_entries():
        assert f"`contracts/{s['name']}.schema.json`" in text and f"`{s['version']}`" in text


def test_docs_schemas_points_at_the_schemas():
    text = (ROOT / "docs/schemas.md").read_text()
    assert "contracts/analysis.schema.json" in text and "part5 contract" in text


def test_ac_c_nfr_01_contract_and_check_run_offline(monkeypatch, capsys):
    def no_network(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert cli.main(["contract", "--json"]) == 0
    assert contract.check(ROOT)["failures"] == []


# ---------------------------------------------------------------- the schemas agree with the loaders
def golden():
    return json.loads(GOLDEN.read_text())


def test_analysis_schema_accepts_both_goldens():
    for path in (GOLDEN, CORRECT):
        assert errors("analysis", json.loads(path.read_text())) == []


def test_analysis_schema_measure_table_matches_part5_measures():
    schema = contract.load_schema("analysis")
    fault = schema["$defs"]["fault"]
    allowed = set(fault["properties"]["measure"]["enum"])
    assert set(GENERIC_MEASURES) <= allowed
    assert allowed - set(GENERIC_MEASURES) <= {"knee_valgus"}  # lands in M2 (ADR-0004)


def fault_for(measure, side):
    f = copy.deepcopy(golden()["faults"][0])
    spec = _spec(measure, side)
    f.update(measure=measure, side=side, measure_kind=spec.kind, body_part=spec.body_part,
             joint=_joint_for(measure, side))
    return f


def doc_with(fault):
    d = golden()
    d["faults"] = [fault]
    if "phrasing" in d:  # one phrasing entry per fault
        d["phrasing"]["faults"] = d["phrasing"]["faults"][:1]
    return d


def agrees(doc):
    """(schema accepts, loader accepts) for one document."""
    try:
        validate_analysis(doc)
        loader = True
    except OutputError:
        loader = False
    return not errors("analysis", doc), loader


@pytest.mark.parametrize("measure", GENERIC_MEASURES)
@pytest.mark.parametrize("side", SIDES)
def test_schema_and_loader_agree_on_every_measure_and_side(measure, side):
    spec = _spec(measure, side)
    if spec is None:  # a side that does not go with the measure
        base = fault_for("upper_arm_out", "left")
        base.update(measure=measure, side=side)
        assert agrees(doc_with(base)) == (False, False)
        return
    good = fault_for(measure, side)
    assert agrees(doc_with(good)) == (True, True)
    wrong_joint = dict(good, joint="nose")
    assert agrees(doc_with(wrong_joint)) == (False, False)
    wrong_part = dict(good, body_part="head" if good["body_part"] != "head" else "arms")
    assert agrees(doc_with(wrong_part)) == (False, False)
    wrong_kind = dict(good, measure_kind="direction" if good["measure_kind"] == "angle" else "angle")
    assert agrees(doc_with(wrong_kind)) == (False, False)


def test_schema_and_loader_agree_on_sign_and_ranges():
    good = golden()["faults"][0]
    cases = [dict(good, direction="less"), dict(good, magnitude_deg=-good["magnitude_deg"]),
             dict(good, unit="radians"), dict(good, threshold_deg=0), dict(good, coverage=1.5),
             dict(good, confidence=-0.1), dict(good, phase=[0.5, 1.2]), dict(good, text="")]
    for bad in cases:
        assert agrees(doc_with(bad)) == (False, False), bad


def test_start_after_end_is_for_the_loader_only():
    """A schema cannot compare two array items; part5.output does."""
    bad = dict(golden()["faults"][0], expected_frames=[5, 3])
    assert agrees(doc_with(bad)) == (True, False)


def test_knee_valgus_is_an_allowed_measure_now():
    f = fault_for("elbow_flexion", "left")
    f.update(measure="knee_valgus", measure_kind="direction", body_part="legs", joint="left_knee")
    assert errors("analysis", doc_with(f)) == []
    assert errors("analysis", doc_with(dict(f, measure_kind="angle")))
    assert errors("analysis", doc_with(dict(f, joint="left_hip")))
    f.update(body_part="arms")
    assert errors("analysis", doc_with(f))


# ---------------------------------------------------------------- the additions of schema 1.1.0
def doc_1_1():
    d = golden()
    d["schema_version"] = "1.1.0"
    d["status"] = {"code": "ok", "text": "Analysed."}
    d["phrasing"] = {"requested": "muse-spark", "backend": "template", "model": None,
                     "fallback_reason": "no key",
                     "faults": [{"backend": "template", "fallback_reason": "no key"}] * len(d["faults"])}
    for f in d["faults"]:
        f["joints"] = ["left_hip", "left_knee"]
        f["runs"] = [f["expected_frames"]]
        f["coaching"] = f["text"]
    d["diagnostics"]["guard"] = {"residual": 0.4, "timing_corr": 0.9, "span_share": 0.8,
                                 "limits": {"max_residual": 1.0, "min_timing_corr": 0.5}}
    return d


def test_a_1_1_document_validates_in_both_validators():
    d = doc_1_1()
    assert errors("analysis", d) == []
    validate_analysis(d)


def test_a_refused_analysis_validates_and_a_refusal_with_faults_does_not():
    d = json.loads(CORRECT.read_text())
    d["schema_version"] = "1.1.0"
    d["status"] = {"code": "different_movement", "text": "This does not look like a squat."}
    d["score"] = None   # a refused take of 1.3.0 or earlier had no score; from 1.4.0 none is refused
    assert errors("analysis", d) == []
    validate_analysis(d)
    refused_with_faults = dict(doc_1_1(), status={"code": "different_movement", "text": "No."})
    assert errors("analysis", refused_with_faults)


@pytest.mark.parametrize("change", [
    lambda d: d.pop("format"),
    lambda d: d.update(format="simon.analysis.v2"),
    lambda d: d.update(status={"code": "maybe", "text": "x"}),
    lambda d: d.update(status={"code": "ok"}),
    lambda d: d.update(schema_version="2.0.0"),
    lambda d: d.update(phrasing={"backend": "gpt"}),
    lambda d: d["faults"][0].update(joints=["spine"]),
    lambda d: d["faults"][0].update(joints=[]),
    lambda d: d["faults"][0].update(runs=[[1]]),
    lambda d: d["diagnostics"].update(follower_span=[1]),
])
def test_analysis_schema_rejects_malformed_additions(change):
    d = doc_1_1()
    change(d)
    assert errors("analysis", d)


def test_analysis_allows_unknown_extra_fields():
    d = doc_1_1()
    d["extra"] = {"anything": 1}
    d["faults"][0]["note"] = "x"
    assert errors("analysis", d) == []


# ---------------------------------------------------------------- labels
def labels_doc():
    take = {"take_id": "exercise_side_good_09_knee_caving-left", "set": "exercise", "movement": "squat",
            "angle": "side", "lighting": "good", "variant": "dropout", "label_source": "synthetic", "seed": 29,
            "correct": False, "faults": [{"type": "knee_caving", "measure": "knee_valgus", "body_part": "legs",
                                          "joints": ["left_knee"], "side": "left", "direction": "more",
                                          "magnitude_deg": 18.0}]}
    correct = {"take_id": "exercise_side_good_00_correct", "correct": True, "faults": []}
    return {"format": "simon.part5.labels.v1", "seed": 29, "label_source": "synthetic", "takes": [take, correct]}


def test_labels_schema_takes_the_new_label_type_and_optional_fields():
    assert errors("labels", labels_doc()) == []


def test_labels_schema_takes_real_take_labels():
    d = labels_doc()
    d.update(label_source="visual", labeller="agent")
    d["takes"][0].update(label_source="visual", expected="fixtures/input/eval/real/side/skeleton.json")
    assert errors("labels", d) == []


@pytest.mark.parametrize("change", [
    lambda d: d["takes"][0].update(variant="noisy"),
    lambda d: d["takes"][0].update(label_source="guess"),
    lambda d: d["takes"][0]["faults"][0].update(type="knee_wobble"),
    lambda d: d["takes"][1].update(faults=d["takes"][0]["faults"]),
    lambda d: d["takes"][0].update(faults=[]),
    lambda d: d["takes"][0]["faults"][0].update(side="middle"),
    lambda d: d.pop("takes"),
    lambda d: d.update(format="simon.part5.labels.v2"),
])
def test_labels_schema_rejects_malformed_labels(change):
    d = labels_doc()
    change(d)
    assert errors("labels", d)


# ---------------------------------------------------------------- input clips
def clip_doc(frames=3, **over):
    doc = {"format": "simon.animation.v1", "fps": 30, "frames": [
        {"index": i, "t": i / 30, "interpolated": False, "joints": {n: [0.01 * j, 0.1 * j, 0.0]
                                                                    for j, n in enumerate(JOINTS)}}
        for i in range(frames)]}
    for f in doc["frames"]:  # keep the hip midpoint at the origin
        f["joints"]["left_hip"], f["joints"]["right_hip"] = [0.1, 0, 0], [-0.1, 0, 0]
    doc.update(over)
    return doc


def test_input_animation_accepts_null_joints_conf_and_a_clip_without_fps_when_t_is_given():
    d = clip_doc()
    d["frames"][1]["joints"]["left_wrist"] = None
    d["frames"][1]["conf"] = {"left_ankle": 0.2, "nose": 1.0}
    assert errors("input-animation", d) == []
    parse_clip(d)
    no_fps = clip_doc()
    del no_fps["fps"]
    assert errors("input-animation", no_fps) == []
    parse_clip(no_fps)


@pytest.mark.parametrize("change", [
    lambda d: d.pop("fps") and [f.pop("t") for f in d["frames"]],
    lambda d: d.update(format="simon.skeleton.v1"),
    lambda d: d.update(fps=0),
    lambda d: d.update(frames=[]),
    lambda d: d.update(joints=["nose"]),
    lambda d: d.update(coordinate_frame={"x": "subject_right"}),
    lambda d: d["frames"][0]["joints"].update(left_toe=[0, 0, 0]),
    lambda d: d["frames"][0]["joints"].update(nose=[0, 0]),
    lambda d: d["frames"][0].update(conf={"nose": 1.5}),
    lambda d: d["frames"][0].pop("joints"),
])
def test_input_animation_rejects_what_part5_io_rejects(change):
    d = clip_doc()
    change(d)
    assert errors("input-animation", d)
    with pytest.raises(ValueError):
        parse_clip(d)


def test_input_skeleton_reads_keyframes_only():
    d = {"format": "simon.skeleton.v1", "fps": 30, "frames": "ignored", "keyframes": [
        {"index": 0, "t": 0.0, "name": "start", "joints": clip_doc(1)["frames"][0]["joints"]}]}
    assert errors("input-skeleton", d) == []
    parse_clip(d)
    del d["keyframes"]
    assert errors("input-skeleton", d)


# ---------------------------------------------------------------- the check-5 document
def metrics_doc():
    sl = {"tp": 4, "fp": 0, "fn": 1, "takes": 9, "correct_takes": 2, "faults_on_correct_takes": 0,
          "precision": 1.0, "recall": 0.8, "refused": 0}
    slices = {"good/front": sl, "good/45": sl, "good/side": sl}
    m = {"format": "simon.part5.metrics.v1", "slices": slices}
    sha = "0" * 64
    return {
        "format": "simon.part5.check.v1", "data_source": "synthetic: held-out takes", "rules_sha256": sha,
        "gate": {"set": "fixtures/input/heldout", "seed": 29, "slices": list(slices),
                 "thresholds": {"precision": 0.85, "recall": 0.75, "faults_on_correct_takes": 0},
                 "passed": True, "failures": [], "metrics": m},
        "attempts": [{"seed": 29, "freeze_commit": "abc1234", "rules_sha256": sha, "approach": "rules",
                      "passed": True, "slices": {}}],
        "tuning": {"set": "fixtures/input/followers", "seed": 5, "gated": False, "metrics": m},
        "report": {"low_light": {"gated": False, "slices": {}}, "dropout": {"gated": False, "slices": {}},
                   "kit": {"gated": False, "source": "Part 3 conformance kit", "takes": []},
                   "stock": {"gated": False, "source": "fixtures/input/eval/real", "takes": [],
                             "note": "not delivered yet"},
                   "refusals": {"good/front": 0}},
    }


def test_metrics_schema_accepts_the_check_document():
    assert errors("metrics", metrics_doc()) == []


@pytest.mark.parametrize("change", [
    lambda d: d.pop("gate"),
    lambda d: d["gate"].update(passed="yes"),
    lambda d: d["gate"]["metrics"]["slices"]["good/front"].update(precision=1.5),
    lambda d: d["report"]["low_light"].update(gated=True),
    lambda d: d["report"]["refusals"].update(gated=True),
    lambda d: d["report"]["refusals"].update(gated="no"),
    lambda d: d["tuning"].update(gated=True),
    lambda d: d.update(rules_sha256="abc"),
    lambda d: d.update(format="simon.part5.metrics.v1"),
])
def test_metrics_schema_rejects_a_malformed_check_document(change):
    d = metrics_doc()
    change(d)
    assert errors("metrics", d)


def test_metrics_1_2_0_accepts_the_refusals_flag_beside_the_slice_counts():
    """AC-K12: report.refusals is slice -> count plus `gated: false`; a 1.1.0 document without it still validates."""
    d = metrics_doc()
    assert "gated" not in d["report"]["refusals"] and errors("metrics", d) == []
    d["report"]["refusals"] = {"gated": False, "good/front": 0, "good/side": 2}
    assert errors("metrics", d) == []


# ---------------------------------------------------------------- the replay and live rows (journey-followup.md J-6)
def test_ac_c02_contract_json_lists_the_replay_schema_and_the_new_rows(capsys):
    assert cli.main(["contract", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    replay = next(s for s in doc["schemas"] if s["name"] == "replay")
    assert replay["version"] == "1.0.0" and replay["file"] == "contracts/replay.schema.json"
    assert replay["schema"]["$id"] == replay["id"] and replay["title"] == "Part 5 replay.json (simon.replay.v1)"
    rows = {r["file"]: r for r in doc["table"]}
    assert rows["`replay.json`"]["format"] == "`simon.replay.v1`" and rows["`replay.json`"]["verdict"] == "works"
    assert "analyse --replay" in rows["`replay.json`"]["producer"]
    live = next(r for r in doc["table"] if r["producer"] == "Part 5 `analyse --live`")
    assert live["verdict"] == "works with an option"
    for word in ("`--live`", "`serve --live`", "`SIMON5_LIVE=1`", "`META_LIVE=1`"):
        assert word in live["file"]
    assert "Baseten key file" in live["fix"] and "template stays the default" in live["fix"]


def test_ac_c02_contract_prints_the_replay_schema_line(capsys):
    assert cli.main(["contract"]) == 0
    out = capsys.readouterr().out
    assert "contracts/replay.schema.json" in out and "simon.replay.v1" in out


def test_ac_c02_contract_md_names_the_replay_file_live_mode_and_the_text_timed_rule():
    text = (ROOT / "CONTRACT.md").read_text()
    for needle in ("`replay.json`", "`simon.replay.v1`", "part5 analyse --expected <file> --follower <file> "
                   "--out <analysis.json> [--replay <replay.json>] [--live]", "`--live`", "`SIMON5_LIVE=1`",
                   "`META_LIVE=1`", "`contracts/replay.schema.json`", "### The replay file", "### Live mode"):
        assert needle in text, needle
    assert "`coaching` equal `text_timed`" in text and "`coaching` equals `text`" not in text
    assert "which is what the tests, `make check-5`, `make check-5-contract` and `make output-examples` always use" in text


def test_ac_c02_the_schema_list_in_contract_md_carries_every_schema_and_version():
    text = (ROOT / "CONTRACT.md").read_text()
    for s in contract.schema_entries():
        assert f"| `{s['name']}` | `{s['version']}` | `contracts/{s['name']}.schema.json` |" in text


# ---------------------------------------------------------------- metrics 1.1.0: the score report
def metrics_with_score():
    d = metrics_doc()
    sl = {"n": 12, "min": 100, "median": 100.0, "max": 100, "grades": {"A": 12}}
    empty = {"n": 0, "min": None, "median": None, "max": None, "grades": {}}
    d["gate"]["sweep"] = {"foot_out right": [[0, 100], [4, 100], [8, 100], [12, 86]],
                          "trunk_lean center": [[0, 100], [5, None]]}
    d["detection_sha256"] = "1" * 64
    d["report"]["score"] = {
        "gated": False, "version": "simon.score.v1",
        "heldout": {"seed": 31, "slices": {"good/0": sl, "low/2": empty},
                    "targets": {"good/0": "pass", "good/1": "fail", "good/2": "no takes"}},
        "tuning": {"seed": 5, "slices": {"good/0": sl}},
        "kit": {"grades": {"B": 3, "F": 1}}, "stock": {"grades": {}}}
    return d


def test_metrics_1_1_0_accepts_the_score_report_check_5_writes():
    assert errors("metrics", metrics_with_score()) == []


def test_metrics_1_1_0_still_accepts_a_1_0_0_document():
    assert errors("metrics", metrics_doc()) == []


@pytest.mark.parametrize("change", [
    lambda d: d["report"]["score"]["heldout"]["slices"]["good/0"]["grades"].update(E=1),
    lambda d: d["report"]["score"]["heldout"]["slices"]["good/0"]["grades"].update(A=-1),
    lambda d: d["report"]["score"]["heldout"]["slices"]["good/0"].pop("median"),
    lambda d: d["report"]["score"]["heldout"]["targets"].update({"good/0": "maybe"}),
    lambda d: d["report"]["score"].update(gated=True),
    lambda d: d["report"]["score"].update(version="simon.score.v2"),
    lambda d: d["report"]["score"].pop("kit"),
    lambda d: d["gate"]["sweep"]["foot_out right"].append([16]),
    lambda d: d["gate"]["sweep"]["foot_out right"].append([16, "high"]),
    lambda d: d.update(detection_sha256="abc"),
])
def test_metrics_1_1_0_rejects_a_malformed_score_report(change):
    d = metrics_with_score()
    change(d)
    assert errors("metrics", d)


def test_contract_json_piped_into_a_reader_that_stops_early_is_quiet_and_exits_0():
    """`part5 contract --json | head` closes the pipe after a few lines; that is not a crash."""
    proc = subprocess.Popen([sys.executable, "-m", "part5", "contract", "--json"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=ROOT)
    first = proc.stdout.readline()
    proc.stdout.close()
    err = proc.stderr.read()
    assert first.strip() == b"{" and proc.wait() == 0
    assert err == b""


# ---------------------------------------------------------------- the feet side file (ADR-0015, input-feet)
FEET_FIXTURES = ROOT / "tests/fixtures/feet"
PART2_PROVENANCE = {"contract_version": "part2.pose3d/2026-10-28", "backend": "gpu",
                    "extra_joints": ["left_big_toe", "left_small_toe", "left_heel", "right_big_toe",
                                     "right_small_toe", "right_heel"]}


def feet_doc(name="side-with-feet.json", **over):
    return {**json.loads((FEET_FIXTURES / name).read_text()), **over}


@pytest.mark.parametrize("provenance", [
    {"source": "synthetic", "generator": "scripts/make_dummy_followers.py", "seed": 5},
    {"source": "synthetic", "generator": "scripts/make_dummy_followers.py", "seed": None},   # a derived example file
    PART2_PROVENANCE,
    {"source": "synthetic", "note": "hand-made"},
])
def test_input_feet_schema_accepts_synthetic_and_part_2_provenance(provenance):
    assert errors("input-feet", feet_doc(provenance=provenance)) == []


def test_input_feet_schema_accepts_the_hand_made_files_a_file_without_extra_joints_and_mirrored():
    assert errors("input-feet", feet_doc()) == [] and errors("input-feet", feet_doc("side-no-feet.json")) == []
    assert errors("input-feet", feet_doc(mirrored=True)) == []
    doc = feet_doc()
    doc["frames"][0]["people"][0]["extra_joints"]["left_heel"] = None   # a point that was not found
    doc["frames"][1]["people"][0]["extra_joints"] = None
    assert errors("input-feet", doc) == []


@pytest.mark.parametrize("change", [
    lambda d: d.update(frames=[]),
    lambda d: d.update(frames={}),
    lambda d: d.update(t0_pts_ms="0"),
    lambda d: d.update(mirrored="yes"),
    lambda d: d.update(provenance=[]),
    lambda d: d["frames"][0].pop("t_ms"),
    lambda d: d["frames"][0].update(people={}),
    lambda d: d["frames"][0]["people"][0].pop("id"),
    lambda d: d["frames"][0]["people"][0].update(id="0"),
    lambda d: d["frames"][0]["people"][0].update(joints=[]),
    lambda d: d["frames"][0]["people"][0].update(extra_joints=[]),
    lambda d: d["frames"][0]["people"][0]["extra_joints"].update(left_heel={"x": "0.1", "y": 0, "z": 0, "conf": 1}),
    lambda d: d["frames"][0]["people"][0]["joints"].update(left_hip={"x": 0, "y": 0, "z": 0, "conf": "high"}),
])
def test_input_feet_schema_rejects_a_file_that_is_not_this_shape(change):
    d = feet_doc()
    change(d)
    assert errors("input-feet", d)


def test_classify_names_a_feet_file_by_its_shape_and_leaves_clips_and_native_alone():
    keys, how = contract.classify("fixtures/input/followers/exercise/t/feet.json", feet_doc())
    assert (keys, how) == (["input-feet"], "feet")
    assert contract.classify("fixtures/input/expected-feet/exercise/feet.json", feet_doc("side-no-feet.json"))[1] == "feet"
    assert contract.classify("x.json", {"frames": [{"joints": {}}], "schema": "simon.skeleton/1"})[1] == "rejected"
    assert contract.classify("x.json", {"frames": [{"people": []}], "format": "simon.animation.v1"})[1] == "clip"
    assert contract.classify("x.json", {"frames": []}) == (None, None)
    assert contract.classify("x.json", {"frames": [{"frame": 0, "t_ms": 0, "joints": {}}]}) == (None, None)


@pytest.fixture
def feet_root(tmp_path):
    """The contract and the three places a feet file lives: a take's folder, the example files and a real take."""
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    for d in ("fixtures/input/expected", "fixtures/input/followers", "fixtures/input/contract", "fixtures/output"):
        (tmp_path / d).mkdir(parents=True)
    for rel, doc in (("fixtures/input/followers/exercise/take/feet.json", feet_doc()),
                     ("fixtures/input/expected-feet/exercise/feet.json",
                      feet_doc("side-no-feet.json", provenance={"source": "synthetic", "generator": "g", "seed": None})),
                     ("fixtures/input/eval/real/pexels/feet.json", feet_doc(provenance=PART2_PROVENANCE))):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(doc))
    return tmp_path


def test_check_validates_and_loads_every_feet_file_in_the_three_places(feet_root):
    summary = contract.check(feet_root)
    assert summary["failures"] == []
    assert summary["validated"]["by_schema"] == {"input-feet": 3} and summary["validated"]["files"] == 3
    assert summary["validated"]["loaded_through_part5"] == 3
    assert any(s["name"] == "input-feet" and s["valid"] for s in summary["schemas"])


def test_check_names_a_feet_file_that_breaks_the_schema_or_the_loader(feet_root):
    bad = feet_root / "fixtures/input/followers/exercise/take/feet.json"
    doc = json.loads(bad.read_text())
    doc["frames"][1]["people"][0]["extra_joints"]["left_heel"]["x"] = "0.07"
    bad.write_text(json.dumps(doc))
    failures = contract.check(feet_root)["failures"]
    assert any(f.startswith("fixtures/input/followers/exercise/take/feet.json") and "input-feet.schema.json" in f
               for f in failures)
    assert any("must be a number or null" in f for f in failures)    # part5.feet reads it the same way


def test_part5_contract_lists_the_feet_schema(capsys):
    assert cli.main(["contract"]) == 0
    assert "input-feet" in capsys.readouterr().out
    assert cli.main(["contract", "--schema", "input-feet"]) == 0
    assert capsys.readouterr().out == (ROOT / "contracts/input-feet.schema.json").read_text()


# ---------------------------------------------------------------- the profile row (ADR-0016, AC-PROF-12)
def test_the_table_and_contract_md_carry_the_profile_row_and_the_analysis_row_names_profile():
    rows = contract.table_rows()
    row = next(r for r in rows if r["file"].startswith("analysis profile"))
    assert row["verdict"] == "works with an option" and row["part5_role"] == "option for Part 7"
    assert "probe `part5 analyse --help` for `--profile`" in row["fix"] and "omitted means `fitness`" in row["fix"]
    analysis = next(r for r in rows if r["file"] == "`analysis.json`")
    assert "1.2.0 to 1.7.0 fields" in analysis["fix"] and "`profile`" in analysis["fix"]
    text = (ROOT / "CONTRACT.md").read_text()
    assert contract.table_markdown([row]).splitlines()[-1] in text
    assert "[--profile {dance,rehab,fitness}]" in text
    assert "9. **Pass the mode, and read a score within its profile.**" in text
    assert any(r["file"].startswith("analysis profile") for r in contract.contract_document()["table"])
