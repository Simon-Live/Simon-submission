"""The real-take report (docs/specs/real-takes.md): AC-R01 to AC-R06, the error cases and the edge cases.

Part 3's kit, Part 2's committed mismatch takes and the guard run for real (about a second for all 18
takes); a stock take is proved on small temp fixtures, since none exists in the repo until simon-part-2
delivers them. Nothing here opens a socket. The import script's tests run only in the firm workspace
(`scripts/` is not published).
"""
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from part5 import cli, real

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / real.KIT_DIR
LABELS_SCHEMA = json.loads((ROOT / "contracts/labels.schema.json").read_text())
SCRIPT = ROOT / "scripts/import-stock-takes.sh"
EXPECTED_STOCK = "fixtures/input/eval/real/pexels-5034562-side/skeleton.json"
FOLLOWER_STOCK = "fixtures/input/eval/real/pexels-5034577-front/skeleton.json"
FULL_SOURCE = """# pexels-5034577-front

- title: Man doing squats in a gym
- licence: Pexels licence
- page URL: https://www.pexels.com/video/5034577/
- author: not stated on the page
- sha256 of the video: 0123456789abcdef
- time_range: 0.0 to 8.0 s

## Imported by Part 5

- part2_commit: 1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
- part3_commit: 2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
- converted by: Part 5 (Claude Code agent)
"""


@pytest.fixture(scope="module")
def report():
    return real.build_report()


@pytest.fixture(scope="module")
def fallback_report():
    """The report as it reads before the stock takes are imported (AC-R04's fallback set)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(real, "stock_takes", lambda root, errors: [])
        return real.build_report()


def by_id(report, take_id):
    return next(t for t in report["takes"] if t["take_id"] == take_id)


def kit_ids():
    return [t["take_id"] for t in json.loads((KIT / "labels.json").read_text())["takes"]]


# ----------------------------------------------------------------- AC-R01
def test_ac_r01_every_kit_take_is_analysed_against_part3_squat(report):
    kit = [t for t in report["takes"] if t["source"] == "part3-kit"]
    assert [t["take_id"] for t in kit] == kit_ids() and len(kit) == 15
    assert {t["expected"] for t in kit} == {"fixtures/input/expected/part3-squat/animation.json"}
    assert all(t["label_source"] == "kit" and t["status"] in ("ok", "different_movement") for t in kit)
    assert all(t["follower"] == f"{real.KIT_DIR}/{t['take_id']}/skeleton.json" for t in kit)


def test_ac_r01_each_take_accounts_for_every_label_and_every_fault(report):
    for t in report["takes"]:
        assert len(t["matched"]) + len(t["missed"]) == len(t["labels"]), t["take_id"]
        assert len(t["matched"]) + len(t["unlabelled"]) == len(t["faults"]), t["take_id"]
        assert set(t["guard"]) >= {"residual", "timing_corr", "span_share"}, t["take_id"]


def test_ac_r01_the_summary_prints_tp_fp_fn_per_kit_type_and_overall(report):
    kit = [t for t in report["takes"] if t["source"] == "part3-kit"]
    s = report["summary"]["kit"]
    assert list(s["by_type"]) == ["feet_wide", "elbows_out", "shallow_squat", "knee_caving", "correct"]
    for kit_type, c in s["by_type"].items():
        rows = [t for t in kit if t["kit_type"] == kit_type]
        assert c["takes"] == len(rows) == 3
        assert (c["tp"], c["fp"], c["fn"]) == (sum(len(t["matched"]) for t in rows),
                                               sum(len(t["unlabelled"]) for t in rows),
                                               sum(len(t["missed"]) for t in rows))
    assert (s["tp"], s["fp"], s["fn"]) == tuple(sum(c[k] for c in s["by_type"].values()) for k in ("tp", "fp", "fn"))
    assert s["takes"] == 15 and s["refused"] == 0
    assert s["precision"] == round(s["tp"] / (s["tp"] + s["fp"]), 4)
    assert s["recall"] == round(s["tp"] / (s["tp"] + s["fn"]), 4)


def test_ac_r01_the_kit_types_the_measures_find_are_found_at_every_angle(report):
    """As measured at the M2 freeze: feet, elbows and depth faults are found on all three takes of a type."""
    by_type = report["summary"]["kit"]["by_type"]
    assert [by_type[k]["tp"] for k in ("feet_wide", "elbows_out", "shallow_squat")] == [3, 3, 3]


def test_ac_r01_a_correct_kit_take_reports_no_fault(report):
    correct = [t for t in report["takes"] if t.get("kit_type") == "correct"]
    assert len(correct) == 3 and all(t["faults"] == [] and t["status"] == "ok" for t in correct)


def test_ac_r01_faults_say_what_where_how_much_and_in_words(report):
    faults = [f for t in report["takes"] for f in t["faults"]]
    assert faults
    for f in faults:
        assert {"measure", "side", "direction", "body_part", "joints", "magnitude_deg", "unit", "text"} <= set(f)
        assert f["joints"] and f["text"]


# ----------------------------------------------------------------- the kit type map on canned analyses
CANNED = {"status": {"code": "ok", "text": ""}, "diagnostics": {"guard": {"residual": 0.1}, "warnings": []}}


def kit_world(tmp_path, monkeypatch, takes):
    """A temp root with a kit of `takes` ((take_id, kit fault dicts, canned faults)) and a canned analyse."""
    kit_dir = tmp_path / real.KIT_DIR
    kit_dir.mkdir(parents=True)
    (kit_dir / "labels.json").write_text(json.dumps({"takes": [
        {"take_id": tid, "angle": "front", "faults": labels} for tid, labels, _ in takes]}))
    for tid, _, _ in takes:
        (kit_dir / tid).mkdir()
        (kit_dir / tid / "skeleton.json").write_text("{}")
    expected = tmp_path / real.KIT_EXPECTED
    expected.parent.mkdir(parents=True)
    expected.write_text("{}")
    canned = {tid: faults for tid, _, faults in takes}
    monkeypatch.setattr(real, "analyse", lambda exp, fol: {
        **CANNED, "faults": canned[fol["take_id"]]})
    return tmp_path


def kit_label(kit_type, side="both"):
    return {"type": kit_type, "measure": "kit_own_measure_name", "body_part": "legs", "side": side,
            "joints": ["left_knee"], "direction": "less", "magnitude_deg": 12.0, "text": kit_type}


def fault(measure, side, direction):
    return {"measure": measure, "side": side, "direction": direction, "body_part": "legs",
            "joints": ["left_knee"], "magnitude_deg": 9.0, "unit": "degrees", "text": f"{measure} {side}"}


@pytest.mark.parametrize("kit_type,measure,direction", [
    ("feet_wide", "foot_out", "more"), ("elbows_out", "upper_arm_out", "more"),
    ("shallow_squat", "knee_flexion", "less"), ("knee_caving", "knee_valgus", "more")])
def test_ac_r01_the_kit_type_map_matches_each_kit_type_to_its_part5_measure(
        tmp_path, monkeypatch, kit_type, measure, direction):
    root = kit_world(tmp_path, monkeypatch, [("t", [kit_label(kit_type, "left")], [fault(measure, "left", direction)])])
    errors = []
    [take] = real.kit_takes(root, errors)
    assert errors == [] and take["kit_type"] == kit_type
    assert [m["measure"] for m in take["matched"]] == [measure] and take["missed"] == []
    assert take["labels"][0]["measure"] == measure and take["labels"][0]["direction"] == direction


def test_ac_r01_a_wrong_measure_or_direction_does_not_match(tmp_path, monkeypatch):
    root = kit_world(tmp_path, monkeypatch, [
        ("wrong_measure", [kit_label("feet_wide")], [fault("upper_arm_out", "both", "more")]),
        ("wrong_direction", [kit_label("feet_wide")], [fault("foot_out", "both", "less")])])
    errors = []
    takes = real.kit_takes(root, errors)
    assert errors == [] and all(t["matched"] == [] and len(t["missed"]) == 1 and len(t["unlabelled"]) == 1 for t in takes)


def test_ac_r01_a_both_label_accepts_either_side_and_a_one_sided_label_does_not(tmp_path, monkeypatch):
    root = kit_world(tmp_path, monkeypatch, [
        ("both_left", [kit_label("shallow_squat", "both")], [fault("knee_flexion", "left", "less")]),
        ("both_right", [kit_label("shallow_squat", "both")], [fault("knee_flexion", "right", "less")]),
        ("left_right", [kit_label("knee_caving", "left")], [fault("knee_valgus", "right", "more")])])
    [a, b, c] = real.kit_takes(root, [])
    assert len(a["matched"]) == 1 and len(b["matched"]) == 1
    assert c["matched"] == [] and len(c["missed"]) == 1 and len(c["unlabelled"]) == 1


def test_ac_r01_an_extra_true_fault_is_listed_as_unlabelled_not_hidden(tmp_path, monkeypatch):
    extra = fault("elbow_flexion", "both", "less")
    root = kit_world(tmp_path, monkeypatch, [
        ("t", [kit_label("elbows_out")], [fault("upper_arm_out", "both", "more"), extra])])
    [take] = real.kit_takes(root, [])
    assert len(take["matched"]) == 1 and [u["measure"] for u in take["unlabelled"]] == ["elbow_flexion"]
    assert (take["matched"][0]["fault_side"], take["matched"][0]["label_side"]) == ("both", "both")


def test_ac_r01_a_refused_kit_take_scores_its_labels_as_misses(tmp_path, monkeypatch):
    root = kit_world(tmp_path, monkeypatch, [("t", [kit_label("feet_wide")], [])])
    monkeypatch.setattr(real, "analyse", lambda exp, fol: {**CANNED, "faults": [],
                                                           "status": {"code": "different_movement", "text": ""}})
    [take] = real.kit_takes(root, [])
    assert take["status"] == "different_movement" and take["matched"] == [] and len(take["missed"]) == 1
    assert real._counts([take])["refused"] == 1


def test_a_kit_type_without_a_part5_measure_is_named(tmp_path, monkeypatch):
    root = kit_world(tmp_path, monkeypatch, [("t", [kit_label("hips_high")], [])])
    errors = []
    assert real.kit_takes(root, errors) == []
    assert errors == ["report-real: t: kit fault type 'hips_high' has no Part 5 measure "
                      "(the kit type map in docs/specs/real-takes.md)"]


# ----------------------------------------------------------------- AC-R02
def test_ac_r02_each_knee_caving_take_says_whether_knee_valgus_was_found(report):
    caving = [t for t in report["takes"] if t.get("kit_type") == "knee_caving"]
    assert [t["take_id"] for t in caving] == ["squat_front_knee_caving-left", "squat_45_knee_caving-right",
                                              "squat_side_knee_caving-left"]
    for t in caving:
        found = any(f["measure"] == "knee_valgus" for f in t["faults"])
        assert isinstance(t["knee_valgus_found"], bool) and t["knee_valgus_found"] == bool(t["matched"])
        if not found:
            assert t["knee_valgus_found"] is False and len(t["missed"]) == 1
    n = sum(t["knee_valgus_found"] for t in caving)
    assert f"knee_valgus was found on {n} of 3 takes, as measured" in " ".join(report["notes"])


def test_ac_r02_only_knee_caving_takes_carry_the_flag(report):
    flagged = {t["take_id"] for t in report["takes"] if "knee_valgus_found" in t}
    assert flagged == {t["take_id"] for t in report["takes"] if t.get("kit_type") == "knee_caving"}


def test_ac_r02_found_and_not_found_are_both_reported(tmp_path, monkeypatch):
    root = kit_world(tmp_path, monkeypatch, [
        ("found", [kit_label("knee_caving", "left")], [fault("knee_valgus", "left", "more")]),
        ("not_found", [kit_label("knee_caving", "left")], [])])
    found, not_found = real.kit_takes(root, [])
    assert found["knee_valgus_found"] is True and found["missed"] == []
    assert not_found["knee_valgus_found"] is False and len(not_found["missed"]) == 1


# ----------------------------------------------------------------- AC-R03: stock takes, once present
def stock_root(tmp_path, *, faults=None, source=FULL_SOURCE, label_source="visual", labeller="a test agent",
               expected=EXPECTED_STOCK, folders=("pexels-5034562-side", "pexels-5034577-front")):
    """A temp root holding one stock follower (a kit take) beside the expected clip (the part3-squat clip)."""
    real_dir = tmp_path / real.STOCK_DIR
    real_dir.mkdir(parents=True)
    for name in folders:
        (real_dir / name).mkdir()
    shutil.copy(ROOT / real.KIT_EXPECTED, real_dir / "pexels-5034562-side" / "skeleton.json")
    if "pexels-5034577-front" in folders:
        shutil.copy(KIT / "squat_front_feet_wide/skeleton.json", real_dir / "pexels-5034577-front" / "skeleton.json")
        if source is not None:
            (real_dir / "pexels-5034577-front" / "SOURCE.md").write_text(source)
    take = {"take_id": "pexels-5034577-front", "set": "stock", "movement": "squat", "angle": "front",
            "camera_yaw_deg": 0, "label_source": label_source, "labeller": labeller, "correct": False,
            "faults": faults if faults is not None else [{
                "type": "foot_out", "measure": "thigh_direction", "body_part": "legs",
                "joints": ["left_ankle", "right_ankle"], "side": "both", "direction": "more",
                "text": "feet turned out"}],
            "expected": expected}
    (real_dir / "labels.json").write_text(json.dumps({
        "format": "simon.part5.labels.v1", "label_source": "visual", "takes": [take]}))
    return tmp_path


def test_ac_r03_a_stock_take_is_scored_against_the_5034562_clip_with_visual_labels(tmp_path):
    errors = []
    [take] = real.stock_takes(stock_root(tmp_path), errors)
    assert errors == []
    assert take["source"] == "stock" and take["label_source"] == "visual"
    assert take["expected"] == EXPECTED_STOCK and take["follower"] == FOLLOWER_STOCK
    assert take["labeller"] == "a test agent" and take["status"] == "ok"
    assert [m["measure"] for m in take["matched"]] == ["foot_out"] and take["missed"] == []
    assert take["provenance"]["missing"] == []


def test_ac_r03_the_source_md_fields_and_both_commits_are_read(tmp_path):
    [take] = real.stock_takes(stock_root(tmp_path), [])
    p = take["provenance"]
    assert p["source_md"] == "fixtures/input/eval/real/pexels-5034577-front/SOURCE.md"
    assert p["part2_commit"] == "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert p["part3_commit"] == "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_ac_r03_part2_commit_is_the_published_one_named_in_the_import_section():
    """Part 2's own SOURCE.md lines may name the commit that produced the files; the import section,
    written after them, names the published upstream commit of Part 2's message, and that one counts."""
    real_root = Path(__file__).resolve().parent.parent
    p = real._provenance(real_root, "pexels-5034577")
    assert p["part2_commit"] == "06f5f8bc3e112ad61a4495d77870101bb649dc1d"


def test_ac_r03_a_source_md_that_lacks_a_field_is_named(tmp_path):
    source = FULL_SOURCE.replace("- part3_commit: 2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n", "")
    source = source.replace("- licence: Pexels licence\n", "")
    [take] = real.stock_takes(stock_root(tmp_path, source=source), [])
    assert take["provenance"]["missing"] == ["licence", "part3_commit"]
    notes = real._notes(tmp_path, [], [take], [])
    assert any("pexels-5034577-front: SOURCE.md lacks licence, part3_commit" in n for n in notes)


def test_ac_r03_a_stock_take_with_no_source_md_lists_every_field(tmp_path):
    [take] = real.stock_takes(stock_root(tmp_path, source=None), [])
    assert [name for name, _ in real.PROVENANCE_FIELDS] == take["provenance"]["missing"]


@pytest.mark.parametrize("label_source", ["synthetic", None])
def test_ac_r03_a_stock_label_must_be_visual(tmp_path, label_source):
    root = stock_root(tmp_path, label_source=label_source)
    labels = json.loads((root / real.STOCK_DIR / "labels.json").read_text())
    del labels["label_source"]
    if label_source is None:
        del labels["takes"][0]["label_source"]
    (root / real.STOCK_DIR / "labels.json").write_text(json.dumps(labels))
    errors = []
    assert real.stock_takes(root, errors) == []
    assert errors == ["report-real: pexels-5034577-front: a stock label needs an expected clip and label_source visual"]


def test_ac_r03_the_label_format_in_the_stock_source_md_validates():
    text = (ROOT / real.STOCK_DIR / "SOURCE.md").read_text()
    example = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
    assert example["label_source"] == "visual"
    doc = {"format": "simon.part5.labels.v1", "takes": [example]}
    assert list(jsonschema.Draft202012Validator(LABELS_SCHEMA).iter_errors(doc)) == []


def test_ac_r03_the_committed_stock_labels_are_visual_and_validate():
    labels = json.loads((ROOT / real.STOCK_DIR / "labels.json").read_text())
    assert labels["label_source"] == "visual" and labels["labeller"]
    assert list(jsonschema.Draft202012Validator(LABELS_SCHEMA).iter_errors(labels)) == []
    assert {"5034562": "expected", "5034577": "follower", "8837221": "follower"} == {
        k: v["role"] for k, v in labels["roles"].items()}
    for take in labels["takes"]:
        assert take["label_source"] == "visual" and (ROOT / take["expected"]).is_file()


def test_ac_r03_a_scored_stock_set_changes_the_notes_and_the_stock_summary(tmp_path):
    for sub in ("contract", "expected", "mismatch"):
        (tmp_path / "fixtures/input").mkdir(parents=True, exist_ok=True)
        (tmp_path / "fixtures/input" / sub).symlink_to(ROOT / "fixtures/input" / sub)
    stock_root(tmp_path)
    doc = real.build_report(tmp_path)
    stock = [t for t in doc["takes"] if t["source"] == "stock"]
    assert [t["take_id"] for t in stock] == ["pexels-5034577-front"]
    s = doc["summary"]["stock"]
    assert (s["tp"], s["fn"], s["takes"]) == (1, 0, 1) and s["fp"] == len(stock[0]["unlabelled"])
    text = " ".join(doc["notes"])
    assert "fallback" not in text and "labels are visual" in text and "a test agent" in text
    assert "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in text
    assert len([t for t in doc["takes"] if t["source"] == "part3-kit"]) == 15  # the kit is still scored


def test_ac_r03_stock_takes_ride_under_report_stock_in_the_check_blocks(tmp_path):
    stock = real.stock_takes(stock_root(tmp_path), [])
    blocks = real.check_blocks({"takes": stock, "notes": ["stock: scored by eye"],
                                "summary": {"kit": {}, "stock": real._counts(stock), "part2": {}}})
    assert blocks["stock"]["takes"][0]["label_source"] == "visual" and blocks["stock"]["note"] == "scored by eye"
    assert blocks["stock"]["gated"] is False and blocks["kit"]["takes"] == []


# ----------------------------------------------------------------- AC-R04
def test_ac_r04_without_stock_the_notes_say_the_fallback_is_used_and_name_part2s_commit(fallback_report):
    report = fallback_report
    sha = re.search(r"Part 2: `moalborati/simon-part-2-images-to-3d` at commit `([0-9a-f]{40})`",
                    (ROOT / real.MISMATCH_DIR / "SOURCE.md").read_text()).group(1)
    stock_notes = [n for n in report["notes"] if n.startswith("stock: ")]
    assert len(stock_notes) == 1
    assert "the fallback set is used" in stock_notes[0] and sha in stock_notes[0]
    assert "5034562" in stock_notes[0] and "5034577" in stock_notes[0] and "8837221" in stock_notes[0]


def test_ac_r04_the_stock_summary_is_all_zeros_without_stock(fallback_report):
    report = fallback_report
    s = report["summary"]["stock"]
    assert (s["tp"], s["fp"], s["fn"], s["takes"], s["refused"]) == (0, 0, 0, 0, 0)
    assert s["precision"] is None and s["recall"] is None
    assert not [t for t in report["takes"] if t["source"] == "stock"]


def test_ac_r04_a_missing_stock_folder_is_the_same_fallback(tmp_path):
    assert real.stock_takes(tmp_path, []) == []


# ----------------------------------------------------------------- AC-R05
def test_ac_r05_every_block_is_marked_not_gated(report):
    assert report["gated"] is False and report["format"] == "simon.part5.real_report.v1"
    blocks = real.check_blocks(report)
    assert blocks["kit"]["gated"] is False and blocks["stock"]["gated"] is False
    unavailable = real.unavailable_blocks("x")
    assert unavailable["kit"]["gated"] is False and unavailable["stock"]["gated"] is False


def test_ac_r05_check_blocks_split_the_kit_from_the_other_real_takes(report, fallback_report):
    stock_ids = [t["take_id"] for t in real.check_blocks(report)["stock"]["takes"]]
    assert stock_ids[-4:] == ["part2-class", "part2-dance", "part2-single", "part2-stretch"]
    assert set(stock_ids[:-4]) == {t["take_id"] for t in report["takes"] if t["source"] in ("stock", "lateral-raise")}
    report = fallback_report
    blocks = real.check_blocks(report)
    assert [t["take_id"] for t in blocks["kit"]["takes"]] == kit_ids()
    assert [t["take_id"] for t in blocks["stock"]["takes"]] == ["pexels-40297504", "pexels-8836968", "part2-class",
                                                                "part2-dance", "part2-single", "part2-stretch"]
    assert blocks["kit"]["summary"] == report["summary"]["kit"]
    assert blocks["stock"]["summary"]["part2"] == report["summary"]["part2"]
    assert "fallback set is used" in blocks["stock"]["note"] and "knee_valgus was found" in blocks["kit"]["note"]
    assert "fallback" not in blocks["kit"]["note"]


# ----------------------------------------------------------------- AC-R06
def test_ac_r06_class_and_dance_are_refused_as_expected(report):
    for name in ("part2-class", "part2-dance", "part2-stretch"):
        t = by_id(report, name)
        assert t["status"] == "different_movement" and t["faults"] == []
        assert t["expected_refusal"] is True and t["refused_as_expected"] is True
        assert t["source"] == "part2-fallback" and t["population"] == "mismatch"
        assert t["expected"] == "fixtures/input/expected/part3-squat/animation.json"
        assert set(t["guard"]) >= {"residual", "timing_corr", "span_share", "limits"}
        assert t["verdict"].startswith("refused as expected")
    assert report["summary"]["part2"] == {"expected_refusals": 3, "refused_as_expected": 3, "matched_references": 1}


def test_ac_r06_the_cli_exits_3_on_each_refused_take(tmp_path, capsys):
    for name in ("part2-class", "part2-dance", "part2-stretch"):
        code = cli.main(["analyse", "--expected", str(ROOT / real.KIT_EXPECTED), "--follower",
                         str(ROOT / real.MISMATCH_DIR / name / "skeleton.json"), "--out", str(tmp_path / "a.json")])
        assert code == 3, name
    capsys.readouterr()


def test_ac_r06_single_is_a_matched_reference_while_it_is_the_provisional_squat(report):
    t = by_id(report, "part2-single")
    manifest = json.loads((ROOT / real.MISMATCH_DIR / "manifest.json").read_text())["fixtures"]["part2-single"]
    assert manifest["population"] == "matched_reference" and "433ae2ed" in manifest["content"]
    assert t["status"] == "ok" and t["expected_refusal"] is False and t["refused_as_expected"] is None
    assert t["labels"] == [] and t["matched"] == [] and t["missed"] == []  # no labels, so no tp or fn
    assert "provisional barbell squat" in t["reason"] and "not an expected refusal" in t["verdict"]
    assert any(n.startswith("part2: part2-single: ") and "provisional barbell squat" in n for n in report["notes"])


def test_ac_r06_a_mismatch_take_the_guard_accepts_is_reported_as_not_refused(tmp_path):
    mismatch = tmp_path / real.MISMATCH_DIR
    mismatch.mkdir(parents=True)
    (mismatch / "part2-single").symlink_to(ROOT / real.MISMATCH_DIR / "part2-single")
    (mismatch / "manifest.json").write_text(json.dumps({"fixtures": {"part2-single": {
        "content": "the seated stretch", "population": "mismatch", "against": real.KIT_EXPECTED}}}))
    expected = tmp_path / real.KIT_EXPECTED
    expected.parent.mkdir(parents=True)
    shutil.copy(ROOT / real.KIT_EXPECTED, expected)
    [t] = real.part2_takes(tmp_path, [])
    assert t["expected_refusal"] is True and t["refused_as_expected"] is False
    assert t["verdict"].startswith("NOT refused")


def test_ac_r06_an_unknown_population_is_named(tmp_path):
    mismatch = tmp_path / real.MISMATCH_DIR
    mismatch.mkdir(parents=True)
    (mismatch / "manifest.json").write_text(json.dumps({"fixtures": {"x": {"population": "other"}}}))
    errors = []
    assert real.part2_takes(tmp_path, errors) == []
    assert "population must be mismatch or matched_reference" in errors[0]


# ----------------------------------------------------------------- error cases
def test_error_a_missing_skeleton_is_named_with_its_take_id(tmp_path, monkeypatch):
    root = kit_world(tmp_path, monkeypatch, [("squat_side_correct", [], [])])
    (root / real.KIT_DIR / "squat_side_correct/skeleton.json").unlink()
    errors = []
    assert real.kit_takes(root, errors) == []
    assert errors == [f"report-real: squat_side_correct: {real.KIT_DIR}/squat_side_correct/skeleton.json not found"]


def test_error_a_label_for_an_unknown_take_names_the_missing_folder(tmp_path):
    root = stock_root(tmp_path, folders=("pexels-5034562-side",))
    errors = []
    assert real.stock_takes(root, errors) == []
    assert errors == ["report-real: labels.json names pexels-5034577-front, no such folder"]


def test_error_a_missing_expected_clip_is_named(tmp_path):
    root = stock_root(tmp_path, expected="fixtures/input/eval/real/pexels-5034562-side/gone.json")
    errors = []
    assert real.stock_takes(root, errors) == []
    assert errors == ["report-real: pexels-5034577-front: fixtures/input/eval/real/pexels-5034562-side/gone.json not found"]


def test_error_a_missing_kit_labels_file_is_named(tmp_path):
    errors = []
    assert real.kit_takes(tmp_path, errors) == []
    assert errors == [f"report-real: kit: {real.KIT_DIR}/labels.json not found"]


def test_error_malformed_labels_json_is_named(tmp_path):
    kit_dir = tmp_path / real.KIT_DIR
    kit_dir.mkdir(parents=True)
    (kit_dir / "labels.json").write_text("{not json")
    errors = []
    assert real.kit_takes(tmp_path, errors) == []
    assert errors[0].startswith(f"report-real: kit: {real.KIT_DIR}/labels.json is not readable JSON")
    (kit_dir / "labels.json").write_text('{"takes": [{"faults": []}]}')
    assert real.kit_takes(tmp_path, errors) == []
    assert errors[1] == f"report-real: {real.KIT_DIR}/labels.json: needs a takes list whose entries each have a take_id"


def test_error_build_report_raises_one_error_naming_every_problem(tmp_path):
    with pytest.raises(real.RealError) as e:
        real.build_report(tmp_path)
    assert e.value.messages == [f"report-real: kit: {real.KIT_DIR}/labels.json not found",
                                f"report-real: part2: {real.MISMATCH_DIR}/manifest.json not found"]


def test_error_the_command_exits_2_and_prints_each_message(monkeypatch, capsys):
    def boom(root=real.ROOT):
        raise real.RealError(["report-real: a: b not found", "report-real: c: d not found"])

    monkeypatch.setattr(real, "build_report", boom)
    assert cli.main(["report-real"]) == 2
    assert capsys.readouterr().err == "report-real: a: b not found\nreport-real: c: d not found\n"


def test_error_the_command_exits_2_when_the_report_cannot_be_written(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert cli.main(["report-real", "--out", str(blocker / "report.json")]) == 2
    assert "report-real: cannot write" in capsys.readouterr().err


# ----------------------------------------------------------------- the command, edge cases, determinism
def test_the_command_writes_the_report_and_prints_a_summary(tmp_path, report, capsys):
    out = tmp_path / "deep/report.json"
    assert cli.main(["report-real", "--out", str(out)]) == 0
    assert json.loads(out.read_text()) == report
    err = capsys.readouterr().err
    assert "report-real: kit 15 takes against part3-squat: tp " in err
    assert "knee_caving" in err and "knee_valgus" in err and "part2-class: different_movement" in err
    assert err.rstrip().endswith(f"report-real: wrote {out}")


def test_edge_a_15_fps_kit_take_is_resampled_onto_the_30_fps_expected_clip(report):
    follower = json.loads((KIT / "squat_front_correct/skeleton.json").read_text())
    expected = json.loads((ROOT / real.KIT_EXPECTED).read_text())
    assert (follower["fps"], expected["fps"]) == (15.0, 30.0)
    t = by_id(report, "squat_front_correct")
    assert t["status"] == "ok" and t["guard"]["span_share"] > 0.9


def test_edge_a_take_that_only_partly_matches_carries_the_span_warning(report):
    warnings = by_id(report, "part2-class")["warnings"]
    assert any("of the follower clip matched the expected movement" in w for w in warnings)
    assert by_id(report, "squat_front_correct")["warnings"] == []


def test_the_report_is_deterministic():
    assert json.dumps(real.build_report()) == json.dumps(real.build_report())


def test_the_report_runs_offline(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("report-real opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    assert real.build_report()["gated"] is False


def test_no_banned_dashes_in_the_text_this_ticket_wrote():
    banned = (chr(0x2014), chr(0x2013))  # em dash, en dash
    for path in (ROOT / "part5/real.py", ROOT / "scripts/import-stock-takes.sh", ROOT / real.STOCK_DIR / "SOURCE.md",
                 ROOT / real.STOCK_DIR / "labels.json"):
        if path.exists():
            assert not any(c in path.read_text() for c in banned), path


# ----------------------------------------------------------------- scripts/import-stock-takes.sh (firm only)
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null"}
FAKE_PART3 = '''import os, shutil, sys
args = sys.argv[1:]
assert args[0] == "run" and "--view" in args and args[args.index("--view") + 1] == "part5", args
with open(os.environ["FAKE_PART3_LOG"], "a") as f:
    f.write(" ".join(args) + "\\n")
if os.environ.get("FAKE_PART3_FAIL"):
    print("part3: cannot read the pose3d", file=sys.stderr)
    sys.exit(1)
out = args[args.index("--out") + 1]
os.makedirs(os.path.dirname(out), exist_ok=True)
shutil.copy(os.environ["FAKE_PART3_SKELETON"], out)
'''


def git(cwd, *args):
    out = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def make_repo(path, files):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "c")
    return git(path, "rev-parse", "HEAD")


def leftovers(imp):
    """The script's own temp directories still on disk (uv leaves its own lock file in TMPDIR; not ours)."""
    return sorted(p.name for p in imp.tmpdir.glob("part5-stock.*"))


class Importer:
    def __init__(self, tmp_path, clips=("pexels-5034562-side", "pexels-5034577-front", "pexels-8837221-45", "other-clip"),
                 with_stock=True, source_md=True):
        self.tmp, self.out = tmp_path, tmp_path / "out"
        self.tmpdir, self.log = tmp_path / "tmp", tmp_path / "part3.log"
        self.tmpdir.mkdir()
        wrapper = tmp_path / "clone"
        wrapper.write_text('#!/bin/sh\nexec git clone -q "$1" "$2"\n')
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        self.wrapper = wrapper
        files = {"README.md": "part 2\n"}
        if with_stock:
            for clip in clips:
                files[f"fixtures/output/stock/{clip}/pose3d.json"] = json.dumps({"clip": clip})
                if source_md:
                    files[f"fixtures/output/stock/{clip}/SOURCE.md"] = f"# {clip}\n\n- title: {clip}\n- licence: Pexels licence\n"
        self.part2 = tmp_path / "part2"
        self.part2_sha = make_repo(self.part2, files)
        self.part3 = tmp_path / "part3"
        self.part3_sha = make_repo(self.part3, {"requirements.txt": "", "part3/__init__.py": "",
                                                "part3/__main__.py": FAKE_PART3})

    def run(self, *args, env=None):
        full = {**os.environ, **GIT_ENV, "TMPDIR": str(self.tmpdir), "STOCK_CLONE": str(self.wrapper),
                "STOCK_PART2_REPO": str(self.part2), "STOCK_PART3_REPO": str(self.part3),
                "STOCK_OUT": str(self.out), "STOCK_PART3_PYTHON": sys.executable,
                "FAKE_PART3_LOG": str(self.log),
                "FAKE_PART3_SKELETON": str(KIT / "squat_front_correct/skeleton.json"), **(env or {})}
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, env=full, capture_output=True, text=True)


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
@pytest.mark.parametrize("args,word", [
    ([], "usage:"), (["not-a-commit"], "must be 7 to 40 lowercase hex"), (["abc"], "must be 7 to 40 lowercase hex"),
    (["abcdef0", "abc"], "[part3_commit] must be"), (["abcdef0", "a", "b"], "usage:")])
def test_script_argument_handling_exits_2_and_writes_nothing(tmp_path, args, word):
    imp = Importer(tmp_path)
    run = imp.run(*args)
    assert run.returncode == 2 and word in run.stderr
    assert not imp.out.exists() and leftovers(imp) == []


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_help_prints_the_header():
    run = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert run.returncode == 0 and "scripts/import-stock-takes.sh <part2_commit>" in run.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_names_a_blocker_and_exits_3_when_the_commit_has_no_stock(tmp_path):
    imp = Importer(tmp_path, with_stock=False)
    run = imp.run(imp.part2_sha)
    assert run.returncode == 3
    assert f"blocker: Part 2 commit {imp.part2_sha} has no fixtures/output/stock/" in run.stderr
    assert not imp.out.exists() and leftovers(imp) == []  # the trap removed the temp dir
    assert not imp.log.exists()  # Part 3 was never run


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_exits_3_when_the_commit_cannot_be_checked_out(tmp_path):
    imp = Importer(tmp_path)
    run = imp.run("deadbeef")
    assert run.returncode == 3 and "cannot clone" in run.stderr and "or check out deadbeef" in run.stderr
    assert leftovers(imp) == []


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_exits_3_when_a_clip_has_no_source_md(tmp_path):
    imp = Importer(tmp_path, source_md=False)
    run = imp.run(imp.part2_sha)
    assert run.returncode == 3 and "published no SOURCE.md for" in run.stderr and not imp.out.exists()


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_exits_3_without_the_expected_clip(tmp_path):
    imp = Importer(tmp_path, clips=("pexels-5034577-front",))
    run = imp.run(imp.part2_sha)
    assert run.returncode == 3 and "has no expected clip (Pexels 5034562, side)" in run.stderr


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_exits_3_when_the_stock_folder_has_no_clip_with_a_role(tmp_path):
    imp = Importer(tmp_path, clips=("other-clip",))
    run = imp.run(imp.part2_sha)
    assert run.returncode == 3 and "no clip for Pexels 5034562, 5034577 or 8837221" in run.stderr


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_ac_r03_script_imports_each_role_with_part2s_fields_and_both_commits(tmp_path):
    imp = Importer(tmp_path)
    run = imp.run(imp.part2_sha[:9], imp.part3_sha)  # an abbreviated Part 2 commit is recorded in full
    assert run.returncode == 0, run.stderr
    assert sorted(p.name for p in imp.out.iterdir()) == ["pexels-5034562-side", "pexels-5034577-front", "pexels-8837221-45"]
    assert "skipping other-clip" in run.stderr and "next: label each follower by eye" in run.stderr
    for clip, role in (("pexels-5034562-side", "expected (side view)"), ("pexels-5034577-front", "follower (front view)"),
                       ("pexels-8837221-45", "follower (three-quarter view)")):
        folder = imp.out / clip
        assert sorted(p.name for p in folder.iterdir()) == ["SOURCE.md", "skeleton.json"]  # no pose3d.json copied
        text = (folder / "SOURCE.md").read_text()
        assert text.startswith(f"# {clip}\n\n- title: {clip}\n- licence: Pexels licence\n")  # Part 2's fields as written
        assert f"- part2_commit: {imp.part2_sha}\n" in text and f"- part3_commit: {imp.part3_sha}\n" in text
        assert f"- role: {role}\n" in text and "converted by: Part 5" in text
        assert json.loads((folder / "skeleton.json").read_text())["format"] == "simon.animation.v1"
    commands = imp.log.read_text().splitlines()
    assert len(commands) == 3 and all(c.startswith("run --in ") and c.endswith("--view part5") for c in commands)
    assert leftovers(imp) == []


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_part3_default_is_the_commit_of_the_contract_lock_file():
    lock = json.loads((ROOT / "contracts/sources.lock.json").read_text())["upstreams"]["part3"]["commit"]
    run = subprocess.run(["bash", "-c", f'source "{SCRIPT}"; is_part3_default'], capture_output=True, text=True)
    assert run.stdout.strip() == lock


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_writes_nothing_when_part3_refuses_a_clip(tmp_path):
    imp = Importer(tmp_path)
    run = imp.run(imp.part2_sha, "main", env={"FAKE_PART3_FAIL": "1"})
    assert run.returncode == 3 and "Part 3 " in run.stderr and "cannot read the pose3d" in run.stderr
    assert not imp.out.exists() and leftovers(imp) == []


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not published")
def test_script_writes_nothing_when_doctor_rejects_the_output(tmp_path):
    imp = Importer(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    run = imp.run(imp.part2_sha, "main", env={"FAKE_PART3_SKELETON": str(bad)})
    assert run.returncode == 3 and "part5 doctor rejects the Part 3 output" in run.stderr and not imp.out.exists()


# ----------------------------------------------------------------- real multi-rep takes (ADR-0010)
def test_the_lateral_raise_followers_are_reported_rep_by_rep(report):
    takes = [t for t in report["takes"] if t["source"] == "lateral-raise"]
    assert [t["take_id"] for t in takes] == ["pexels-40297504", "pexels-8836968"]
    for t in takes:
        assert t["status"] == "ok" and t["score"] is not None and t["expected_reference"]["kind"] == "first_rep"
        assert t["reps"] and all(r["ok"] for r in t["reps"]) and t["label_source"] == "none"
    assert [len(t["reps"]) for t in takes] == [8, 2]
    assert report["summary"]["reps"] == {"takes": 2, "accepted": 2, "reps": 10, "reps_passed": 10}
    assert sum(n.startswith("reps: ") for n in report["notes"]) == 2
