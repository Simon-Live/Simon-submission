"""`make check-5` (docs/specs/check-5.md): the gate, the reported slices, attempts, exit codes.

The analyse step is replaced by a table of analyses, so no held-out data is needed and nothing
here generates or scores a held-out seed. One test runs the real pipeline offline on seed 5 takes.
The score gate and the score freeze (AC-S04, AC-S06, AC-K10) are in tests/test_check_score.py, and the freeze of the
detection rules, the order of the seeds and the attempts record (AC-K07 to AC-K09, B3, R7) in tests/test_check_freeze.py;
both build on the synthetic world defined here.
"""
import hashlib
import json
import re
import shutil
import socket
import time
from pathlib import Path

import jsonschema
import pytest

from part5 import check, profiles

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts/metrics.schema.json").read_text())
ANGLES = ("front", "45", "side")

SLICE = {"tp": 9, "fp": 1, "fn": 2, "takes": 8, "correct_takes": 2, "faults_on_correct_takes": 0,
         "precision": 0.9, "recall": 0.8182}


# ----------------------------------------------------------------- the gate on metrics
def metrics(**overrides):
    m = {"slices": {name: dict(SLICE) for name in check.GATED + ("low/side",)}}
    for name, fields in overrides.items():
        m["slices"][name.replace("_", "/")].update(fields)
    return m


def test_all_good_slices_passing_passes_even_if_low_light_is_bad():
    g = check.gate(metrics(low_side={"precision": 0.1, "recall": 0.1, "faults_on_correct_takes": 9}))
    assert g["passed"] and g["failures"] == []


def test_ac_k01_each_gated_slice_and_criterion_can_fail_on_its_own():
    for name in check.GATED:
        key = name.replace("/", "_")
        for fields, word in (({"precision": 0.84}, "precision 0.84 is below 0.85"),
                             ({"recall": 0.74}, "recall 0.74 is below 0.75"),
                             ({"faults_on_correct_takes": 1}, "1 fault(s) on correct takes")):
            g = check.gate(metrics(**{key: fields}))
            assert not g["passed"] and g["gated_slices"][name] is False
            assert g["failures"] == [f"{name}: {word}"]


def test_thresholds_are_inclusive():
    g = check.gate(metrics(good_front={"precision": 0.85, "recall": 0.75}))
    assert g["passed"]


def test_ac_k02_a_missing_gated_slice_fails():
    m = metrics()
    del m["slices"]["good/45"]
    g = check.gate(m)
    assert not g["passed"] and "good/45: no takes" in g["failures"]


def test_ac_k02_a_slice_with_no_labelled_faults_fails_instead_of_scoring_recall_1():
    g = check.gate(metrics(good_side={"tp": 0, "fn": 0, "fp": 0, "precision": 1.0, "recall": 1.0}))
    assert not g["passed"] and g["failures"] == ["good/side: no labelled faults, so recall can't be measured"]


def test_ac_k02_a_slice_with_no_correct_takes_fails():
    g = check.gate(metrics(good_45={"correct_takes": 0}))
    assert not g["passed"]
    assert g["failures"] == ["good/45: no correct takes, so faults on correct takes can't be measured"]


A_SCORE = {"version": "simon.score.v1", "value": 95, "grade": "A",
           "components": {"faults": 5.0, "similarity": 0.0}, "params_sha256": "d" * 64}
RISING_FREE_SWEEP = {"foot_out right": [(0, 100), (4, 100), (8, 90)], "trunk_lean center": [(0, 100), (5, 87)]}


# ----------------------------------------------------------------- a synthetic world
def fault_label(side="left"):
    return {"type": "arms_wider", "measure": "upper_arm_direction", "body_part": "arms", "side": side,
            "direction": "more"}


def hit(side="left"):
    return {"measure": "upper_arm_out", "side": side, "direction": "more"}


def wrong():
    return {"measure": "knee_flexion", "side": "left", "direction": "less"}


def labelled(tid, angle, light, variant, faults):
    return {"take_id": tid, "set": "exercise", "angle": angle, "lighting": light, "variant": variant,
            "correct": not faults, "faults": faults, "expected": "exp.json", "follower": f"{tid}.json"}


WARNING = [{"code": "low_match", "text": "x"}]


def cell(prefix, angle, light, *, variant="clean", correct=2, faulty=4, miss=0, refuse=0, extra=0, wrong_correct=0,
         warn=0, warned_correct=0):
    """Takes and their analyses for one slice: `faulty` fault takes (the first `refuse` refused, the next `warn`
    analysed with a warning that still lists the right fault, the next `miss` missed, the last also carries
    `extra` spurious faults) and `correct` takes (the first `warned_correct` carry a warning, the next
    `wrong_correct` get a spurious fault)."""
    takes, analyses = [], {}
    for i in range(correct):
        tid = f"{prefix}_{angle}_{light}_{variant}_c{i}"
        takes.append(labelled(tid, angle, light, variant, []))
        analyses[tid] = {"faults": [wrong()] if warned_correct <= i < warned_correct + wrong_correct else [],
                         "status": {"code": "ok"}}
        if i < warned_correct:
            analyses[tid]["warnings"] = WARNING
    for i in range(faulty):
        tid = f"{prefix}_{angle}_{light}_{variant}_f{i}"
        takes.append(labelled(tid, angle, light, variant, [fault_label()]))
        if i < refuse:
            analyses[tid] = {"faults": [], "status": {"code": "different_movement"}}
        elif i < refuse + warn:   # ADR-0012: status ok, the warning says why it is graded F, the fault is still listed
            analyses[tid] = {"faults": [hit()], "status": {"code": "ok"}, "warnings": WARNING}
        elif i < refuse + warn + miss:
            analyses[tid] = {"faults": [], "status": {"code": "ok"}}
        else:
            spurious = [wrong() for _ in range(extra)] if i == faulty - 1 else []
            analyses[tid] = {"faults": [hit()] + spurious, "status": {"code": "ok"}}
    return takes, analyses


def green(prefix, overrides=None, dropout=True):
    """Every slice passing: good and low light at three angles, plus dropout copies at 45 and side."""
    overrides = overrides or {}
    takes, analyses = [], {}
    cells = [(a, l, "clean") for a in ANGLES for l in ("good", "low")]
    cells += [(a, l, "dropout") for a in ("45", "side") for l in ("good", "low")] if dropout else []
    for angle, light, variant in cells:
        t, a = cell(prefix, angle, light, variant=variant, **overrides.get((angle, light, variant), {}))
        takes += t
        analyses.update(a)
    return takes, analyses


REAL_SCORE_RECORD = ROOT / "fixtures" / "score-heldout.json"


def shipped_score_record():
    """A score record that freezes the `score` block part5/rules.json ships, as the real record does: a v2 block by a
    `freezes` entry (simon.score.v2, ADR-0018) beside the v1 attempts of seeds 47 and 53 (their hash is the frozen v1
    block's, not the v2 freeze's), a v1 block by its attempt (ADR-0007). The committed fixtures/score-heldout.json holds the
    v2 freeze only once the orchestrator records it; the check's own tests do not wait for that."""
    hash_of = lambda b: hashlib.sha256(json.dumps(b, sort_keys=True, separators=(",", ":")).encode()).hexdigest()   # noqa: E731
    block = json.loads((ROOT / "part5/rules.json").read_text())["score"]
    v1_sha = hash_of(block.get("v1", block))
    freezes = [{"version": block["version"], "params_sha256": hash_of(block), "seed": 59}] if "v1" in block else []
    return {"format": "simon.part5.score-heldout.v1", "attempts": [{"seed": 47, "params_sha256": v1_sha}], "freezes": freezes}


class World:
    def __init__(self, tmp_path, monkeypatch):
        self.root, self.monkeypatch = tmp_path, monkeypatch
        self.analyses = {}
        if check.SCORE_RECORD == REAL_SCORE_RECORD:   # a test that set its own record keeps it
            (tmp_path / "score-heldout.json").write_text(json.dumps(shipped_score_record()))
            monkeypatch.setattr(check, "SCORE_RECORD", tmp_path / "score-heldout.json")
        monkeypatch.setattr(check, "ROOT", tmp_path)
        monkeypatch.setattr(check, "HELDOUT", tmp_path / "heldout")
        monkeypatch.setattr(check, "TUNING", tmp_path / "followers")
        monkeypatch.setattr(check, "ATTEMPTS", tmp_path / "attempts.json")
        monkeypatch.setattr(check, "THRESHOLDS_DOC", tmp_path / "thresholds.md")
        monkeypatch.setattr(check, "OUT_DIR", tmp_path / "out")
        monkeypatch.setattr(check, "analyse", self.analyse)
        monkeypatch.setattr(check, "run_sweep", lambda out_dir: dict(RISING_FREE_SWEEP))
        (tmp_path / "exp.json").write_text("{}")

    def analyse(self, expected, follower):
        a = self.analyses[follower["take_id"]]
        if "score" not in a:  # ADR-0007: every ok take carries a score; a refused one has none
            a = {**a, "score": A_SCORE if a["status"]["code"] == "ok" else None}
        return a

    def add(self, directory, seed, takes, analyses):
        d = self.root / directory
        d.mkdir(exist_ok=True)
        (d / "labels.json").write_text(json.dumps({"format": "simon.part5.labels.v1", "seed": seed, "takes": takes}))
        for t in takes:
            (self.root / t["follower"]).write_text("{}")
        self.analyses.update(analyses)

    def attempts(self, entries):
        (self.root / "attempts.json").write_text(json.dumps({"format": "x", "attempts": entries}))

    def run(self, capsys, *args):
        code = check.main(list(args))
        out, err = capsys.readouterr()
        return code, out, err


RULES_SHA = hashlib.sha256((ROOT / "part5/rules.json").read_bytes()).hexdigest()


def freeze_section(seed, sha=RULES_SHA):
    return f"## Attempt 1: seed {seed}\nFreeze commit: `abc1234`\nrules_sha256: `{sha}`\nApproach family: rule maths\n"


def world(tmp_path, monkeypatch, seed=29, held=None, tuning=None):
    """A temp world whose docs/thresholds.md freezes the real rules.json for `seed`, unless the test wrote its own."""
    w = World(tmp_path, monkeypatch)
    w.add("heldout", seed, *(held or green("h")))
    w.add("followers", 5, *(tuning or green("t", dropout=False)))
    if not (tmp_path / "thresholds.md").exists():
        (tmp_path / "thresholds.md").write_text(freeze_section(seed))
    return w


def errors_of(doc):
    return [e.message for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc)]


# ----------------------------------------------------------------- AC-K01 to AC-K09
def test_ac_k01_precision_below_the_bar_exits_1_and_names_the_slice_and_number(tmp_path, monkeypatch, capsys):
    held = green("h", {("45", "good", "clean"): {"extra": 1}})  # 4 hits and 1 spurious fault: 4 / 5
    code, out, err = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    assert code == 1 and doc["gate"]["passed"] is False
    assert doc["gate"]["failures"] == ["good/45: precision 0.8 is below 0.85"]
    assert "good/45" in err and "check-5: FAIL (1 criteria)" in err


def test_ac_k01_a_green_gate_exits_0(tmp_path, monkeypatch, capsys):
    code, out, err = world(tmp_path, monkeypatch).run(capsys)
    doc = json.loads(out)
    assert code == 0 and doc["gate"]["passed"] is True and doc["gate"]["failures"] == []
    assert err.strip().splitlines()[-1] == "check-5: PASS"
    assert doc["gate"]["slices"] == ["good/front", "good/45", "good/side"]
    assert doc["gate"]["thresholds"] == {"precision": 0.85, "recall": 0.75, "faults_on_correct_takes": 0}


@pytest.mark.parametrize("overrides,sentence", [
    ({"correct": 0}, "good/side: no correct takes, so faults on correct takes can't be measured"),
    ({"faulty": 0}, "good/side: no labelled faults, so recall can't be measured"),
])
def test_ac_k02_an_empty_gated_slice_exits_1(tmp_path, monkeypatch, capsys, overrides, sentence):
    held = green("h", {("side", "good", "clean"): overrides})
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    assert code == 1 and sentence in json.loads(out)["gate"]["failures"]


def test_ac_k02_a_gated_slice_with_no_takes_at_all_exits_1(tmp_path, monkeypatch, capsys):
    takes, analyses = green("h")
    takes = [t for t in takes if not (t["angle"] == "45" and t["lighting"] == "good" and t["variant"] == "clean")]
    code, out, _ = world(tmp_path, monkeypatch, held=(takes, analyses)).run(capsys)
    assert code == 1 and "good/45: no takes" in json.loads(out)["gate"]["failures"]


def test_ac_k03_reported_slices_never_gate(tmp_path, monkeypatch, capsys):
    """Low light at precision 0.3, dropout at recall 0.5 and a kit take with every label missed."""
    held = green("h", {
        ("front", "low", "clean"): {"extra": 5, "wrong_correct": 2},
        ("45", "low", "clean"): {"extra": 5, "wrong_correct": 2},
        ("side", "low", "clean"): {"extra": 5, "wrong_correct": 2},
        ("45", "good", "dropout"): {"miss": 2}, ("side", "good", "dropout"): {"miss": 2},
        ("45", "low", "dropout"): {"miss": 2}, ("side", "low", "dropout"): {"miss": 2}})
    w = world(tmp_path, monkeypatch, held=held)
    kit = {"kit": {"gated": False, "source": "Part 3 conformance kit",
                   "takes": [{"take_id": "squat_front_knee_caving-left", "labelled": 1, "found": 0}]},
           "stock": {"gated": False, "source": "fixtures/input/eval/real", "takes": [], "note": "not delivered"}}
    monkeypatch.setattr(check, "real_blocks", lambda root=None: kit)
    code, out, _ = w.run(capsys)
    doc = json.loads(out)
    assert code == 0 and doc["gate"]["passed"]
    low, drop = doc["report"]["low_light"], doc["report"]["dropout"]
    assert low["gated"] is False and drop["gated"] is False and doc["report"]["kit"]["gated"] is False
    assert all(s["precision"] < 0.5 for s in low["slices"].values())
    assert set(drop["slices"]) == {"dropout/45", "dropout/side"}
    assert all(s["recall"] == 0.5 for s in drop["slices"].values())
    assert doc["report"]["kit"]["takes"][0]["found"] == 0
    assert doc["tuning"]["gated"] is False


def test_ac_k04_a_refused_take_counts_per_slice_and_its_labels_are_misses(tmp_path, monkeypatch, capsys):
    held = green("h", {("front", "good", "clean"): {"refuse": 1}})
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    front = doc["gate"]["metrics"]["slices"]["good/front"]
    assert front["refused"] == 1 and front["fn"] == 1 and front["tp"] == 3 and front["recall"] == 0.75
    assert doc["gate"]["metrics"]["slices"]["good/45"]["refused"] == 0
    assert doc["report"]["refusals"]["good/front"] == 1 and doc["report"]["refusals"]["good/45"] == 0
    assert doc["gate"]["metrics"]["by_lighting"]["good"]["refused"] == 1
    assert code == 0  # a refusal is reported and lowers recall; it is never a failure by itself


def test_ac_k04_a_take_analysed_with_a_warning_counts_per_slice_and_its_labels_are_misses(tmp_path, monkeypatch, capsys):
    """ADR-0012: status ok plus `warnings`; the fault it still lists is no prediction, and the row says refused."""
    held = green("h", {("front", "good", "clean"): {"warn": 1}})
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    front = doc["gate"]["metrics"]["slices"]["good/front"]
    assert (front["refused"], front["fn"], front["tp"], front["fp"], front["recall"]) == (1, 1, 3, 0, 0.75)
    assert doc["report"]["refusals"]["good/front"] == 1 and doc["report"]["refusals"]["good/45"] == 0
    assert code == 0
    rows = json.loads((tmp_path / "out" / "takes.json").read_text())
    warned = [r for r in rows if r["set"] == "heldout" and r["refused"]]
    assert [r["take_id"] for r in warned] == ["h_front_good_clean_f0"] and warned[0]["predicted"] != []


def test_ac_k04_a_warned_correct_take_is_a_fault_on_a_correct_take_and_fails_the_gate(tmp_path, monkeypatch, capsys):
    held = green("h", {("45", "good", "clean"): {"warned_correct": 1}})
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    assert code == 1 and doc["gate"]["failures"] == ["good/45: 1 fault(s) on correct takes"]
    assert doc["gate"]["metrics"]["slices"]["good/45"]["refused"] == 1


def test_ac_k04_refusals_that_pull_recall_under_the_bar_fail_through_recall_only(tmp_path, monkeypatch, capsys):
    held = green("h", {("side", "good", "clean"): {"refuse": 2}})
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    assert code == 1 and doc["gate"]["failures"] == ["good/side: recall 0.5 is below 0.75"]
    assert doc["report"]["refusals"]["good/side"] == 2


def test_ac_k07_every_recorded_hash_line_in_thresholds_md_holds_a_real_hash():
    """The attempt template in the file must not start a line with a hash label: a grep prints real values only."""
    text = (ROOT / "docs/thresholds.md").read_text()
    lines = [ln for ln in text.splitlines() if ln.startswith(("rules_sha256:", "detection_sha256:"))]
    assert len(lines) >= 3
    assert all(re.fullmatch(r"(rules|detection)_sha256: `[0-9a-f]{64}`", ln) for ln in lines), lines
    assert check.recorded_detection_hash(text) == check.detection_hash()


def test_ac_k12_every_report_block_carries_gated_false_and_refusals_keeps_its_slice_counts(tmp_path, monkeypatch, capsys):
    """The six report blocks all say gated false; `refusals` stays slice -> count with that one extra key."""
    held = green("h", {("side", "good", "clean"): {"refuse": 2}})
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    report = doc["report"]
    assert set(report) == {"low_light", "dropout", "kit", "stock", "refusals", "score"}
    assert [name for name, block in report.items() if block["gated"] is not False] == []
    counts = {k: v for k, v in report["refusals"].items() if k != "gated"}
    assert counts == {k: v["refused"] for k, v in doc["gate"]["metrics"]["slices"].items()}
    assert counts["good/side"] == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in counts.values())
    assert errors_of(doc) == [] and code == 1  # recall fails the gate; the flag changes no gate figure


def test_ac_k12_a_1_1_0_document_without_the_refusals_flag_still_validates_and_a_true_flag_does_not():
    base = {"low_light": {"gated": False}, "dropout": {"gated": False}, "kit": {"gated": False},
            "stock": {"gated": False}, "refusals": {"good/front": 0}}
    validator = jsonschema.Draft202012Validator(SCHEMA["properties"]["report"])
    assert SCHEMA["version"] == "1.4.0" and list(validator.iter_errors(base)) == []
    assert list(validator.iter_errors({**base, "refusals": {"gated": False, "good/front": 0}})) == []
    assert list(validator.iter_errors({**base, "refusals": {"gated": True, "good/front": 0}}))
    assert list(validator.iter_errors({**base, "refusals": {"gated": False, "good/front": -1}}))


def test_ac_k04_a_refused_correct_take_is_a_fault_on_a_correct_take_and_fails_the_gate(tmp_path, monkeypatch, capsys):
    takes, analyses = green("h")
    correct = next(t["take_id"] for t in takes if t["correct"] and (t["angle"], t["lighting"]) == ("45", "good"))
    analyses[correct] = {"faults": [], "status": {"code": "different_movement"}}
    code, out, _ = world(tmp_path, monkeypatch, held=(takes, analyses)).run(capsys)
    doc = json.loads(out)
    assert code == 1 and doc["gate"]["failures"] == ["good/45: 1 fault(s) on correct takes"]
    assert doc["gate"]["metrics"]["slices"]["good/45"]["refused"] == 1


def test_ac_k05_stdout_is_one_json_document_that_validates(tmp_path, monkeypatch, capsys):
    code, out, err = world(tmp_path, monkeypatch).run(capsys)
    doc = json.loads(out)  # the whole of stdout parses: nothing else was printed there
    assert errors_of(doc) == [] and doc["format"] == "simon.part5.check.v1"
    assert out.startswith("{\n  ") and out.endswith("}\n")
    assert "check-5:" in err and "{" not in err


def test_ac_k06_two_runs_are_byte_identical(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    first, second = w.run(capsys)[1], w.run(capsys)[1]
    assert first == second and first


def test_ac_k07_names_the_tuning_seed_the_gate_seed_and_the_rules(tmp_path, monkeypatch, capsys):
    sha = RULES_SHA
    (tmp_path / "thresholds.md").write_text(freeze_section(29))
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    doc = json.loads(out)
    assert doc["tuning"]["seed"] == 5 and doc["tuning"]["set"].endswith("followers")
    assert doc["gate"]["seed"] == 29 == json.loads((tmp_path / "heldout/labels.json").read_text())["seed"]
    assert doc["rules_sha256"] == sha == doc["attempts"][-1]["rules_sha256"]
    assert doc["attempts"][-1]["freeze_commit"] == "abc1234" and doc["attempts"][-1]["approach"] == "rule maths"
    assert "warning" not in err


# ----------------------------------------------------------------- the rest of the document
def test_the_dropout_copies_report_as_dropout_slices_and_stay_out_of_the_gate(tmp_path, monkeypatch, capsys):
    """AC-008 (check side): dropout/<angle> slices are reported; good-light slices hold clean takes only."""
    code, out, _ = world(tmp_path, monkeypatch).run(capsys)
    doc = json.loads(out)
    assert set(doc["report"]["dropout"]["slices"]) == {"dropout/45", "dropout/side"}
    assert doc["report"]["dropout"]["slices"]["dropout/45"]["takes"] == 12  # 2 lights x 6 takes
    assert doc["gate"]["metrics"]["slices"]["good/45"]["takes"] == 6
    assert set(doc["report"]["low_light"]["slices"]) == {"low/front", "low/45", "low/side"}


def test_tuning_metrics_cover_the_whole_seed_5_set_and_never_gate(tmp_path, monkeypatch, capsys):
    tuning = green("t", {("side", "good", "clean"): {"miss": 4, "extra": 3}}, dropout=False)
    code, out, _ = world(tmp_path, monkeypatch, tuning=tuning).run(capsys)
    doc = json.loads(out)
    assert code == 0 and doc["tuning"]["gated"] is False
    assert doc["tuning"]["metrics"]["slices"]["good/side"]["recall"] == 0.0
    assert "low/front" in doc["tuning"]["metrics"]["slices"]


def test_kit_and_stock_blocks_are_present_and_say_why_they_are_empty(tmp_path, monkeypatch, capsys):
    """The temp world has no real-take fixtures: the blocks stay empty, name the missing file and never fail the check."""
    code, out, _ = world(tmp_path, monkeypatch).run(capsys)
    report = json.loads(out)["report"]
    assert code == 0
    assert report["kit"]["gated"] is False and report["kit"]["takes"] == []
    assert "real-take report not available" in report["kit"]["note"] and "labels.json not found" in report["kit"]["note"]
    assert report["stock"]["gated"] is False and report["stock"]["takes"] == [] and report["stock"]["note"]
    assert report["stock"]["source"] == "fixtures/input/eval/real"


def test_kit_and_stock_blocks_carry_the_real_take_report(tmp_path, monkeypatch, capsys):
    """AC-R01, AC-R03: against the repo's fixtures the blocks hold the 15 kit takes, the stock takes and
    Part 2's takes (the fallback set alone, without stock, is tested in tests/test_real.py)."""
    real_root = Path(check.__file__).resolve().parent.parent
    blocks = check.real_blocks(real_root)
    kit, stock = blocks["kit"], blocks["stock"]
    assert kit["gated"] is False and stock["gated"] is False
    assert kit["source"] == "Part 3 conformance kit" and stock["source"] == "fixtures/input/eval/real"
    assert len(kit["takes"]) == 15 and {t["source"] for t in kit["takes"]} == {"part3-kit"}
    assert set(kit["summary"]["by_type"]) == {"feet_wide", "elbows_out", "shallow_squat", "knee_caving", "correct"}
    ids = [t["take_id"] for t in stock["takes"]]
    assert ids[-4:] == ["part2-class", "part2-dance", "part2-single", "part2-stretch"]
    assert {t["source"] for t in stock["takes"][:-4]} == {"stock", "lateral-raise"} and len(ids) > 4
    assert all(t["label_source"] == ("none" if t["source"] == "lateral-raise" else "visual") for t in stock["takes"][:-4])
    report = {"low_light": {"gated": False}, "dropout": {"gated": False}, **blocks, "refusals": {}}
    assert [e.message for e in jsonschema.Draft202012Validator(SCHEMA["properties"]["report"]).iter_errors(report)] == []


def test_ac_r05_every_real_take_missed_still_exits_on_the_gate_alone(tmp_path, monkeypatch, capsys):
    """Every kit label missed and a Part 2 mismatch take accepted: the gate is green, so exit 0."""
    missed = {"labels": [{"type": "feet_wide"}], "matched": [], "missed": [{"type": "feet_wide"}], "faults": [],
              "unlabelled": [], "status": "ok", "guard": {}}
    report = {"gated": False, "takes": [
        {"take_id": "kit-a", "source": "part3-kit", **missed},
        {"take_id": "part2-class", "source": "part2-fallback", "expected_refusal": True, "refused_as_expected": False,
         **missed}],
        "summary": {"kit": {"tp": 0, "fp": 0, "fn": 1}, "stock": {"tp": 0, "fp": 0, "fn": 0},
                    "part2": {"expected_refusals": 1, "refused_as_expected": 0, "matched_references": 0}},
        "notes": ["kit: all missed", "stock: nothing"]}
    monkeypatch.setattr(check.real, "build_report", lambda root=None: report)
    w = world(tmp_path, monkeypatch)
    code, out, err = w.run(capsys)
    doc = json.loads(out)
    assert code == 0 and doc["gate"]["passed"] is True and err.strip().splitlines()[-1] == "check-5: PASS"
    assert errors_of(doc) == []
    assert doc["report"]["kit"]["takes"][0]["missed"] and doc["report"]["kit"]["gated"] is False
    assert doc["report"]["stock"]["takes"][0]["refused_as_expected"] is False


def test_ac_r05_a_failing_real_report_leaves_the_gate_to_decide(tmp_path, monkeypatch, capsys):
    def broken(root=None):
        raise check.real.RealError(["report-real: squat_front_correct: some/file.json not found"])

    monkeypatch.setattr(check.real, "build_report", broken)
    code, out, _ = world(tmp_path, monkeypatch).run(capsys)
    report = json.loads(out)["report"]
    assert code == 0 and report["kit"]["takes"] == [] and report["stock"]["takes"] == []
    assert "squat_front_correct: some/file.json not found" in report["kit"]["note"]
    assert errors_of(json.loads(out)) == []


def test_ac_r05_a_red_gate_still_fails_with_real_blocks_present(tmp_path, monkeypatch, capsys):
    held = green("h", {("45", "good", "clean"): {"extra": 1}})
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    assert code == 1 and json.loads(out)["gate"]["failures"] == ["good/45: precision 0.8 is below 0.85"]


def test_data_source_says_the_gate_is_synthetic(tmp_path, monkeypatch, capsys):
    doc = json.loads(world(tmp_path, monkeypatch).run(capsys)[1])
    assert doc["data_source"].startswith("synthetic: held-out takes (seed 29")
    assert "tuned on seed 5 only" in doc["data_source"]


def test_the_json_is_also_written_to_out_and_a_per_take_report_beside_it(tmp_path, monkeypatch, capsys):
    code, out, _ = world(tmp_path, monkeypatch).run(capsys)
    assert (tmp_path / "out/metrics.json").read_text() == out
    rows = json.loads((tmp_path / "out/takes.json").read_text())
    assert {r["set"] for r in rows} == {"heldout", "tuning"}
    assert all({"take_id", "slice", "refused", "predicted", "labelled"} <= set(r) for r in rows)
    assert not (tmp_path / "out/takes.json").read_text().startswith("{")  # a list, never part of the gate document


def test_json_out_chooses_the_file(tmp_path, monkeypatch, capsys):
    target = tmp_path / "elsewhere" / "m.json"
    code, out, _ = world(tmp_path, monkeypatch).run(capsys, "--json-out", str(target))
    assert target.read_text() == out and not (tmp_path / "out/metrics.json").exists()


def test_set_chooses_the_held_out_directory(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=29)
    (tmp_path / "heldout").rename(tmp_path / "other")
    code, out, _ = w.run(capsys, "--set", str(tmp_path / "other"))
    assert code == 0 and json.loads(out)["gate"]["set"] == "other"


# ----------------------------------------------------------------- attempts file and thresholds record
def test_the_committed_attempts_file_has_the_published_format():
    doc = json.loads((ROOT / "fixtures/heldout-attempts.json").read_text())
    assert doc["format"] == "simon.part5.heldout_attempts.v1" and isinstance(doc["attempts"], list)
    seeds = [a["seed"] for a in doc["attempts"]]
    assert seeds == list(check.HELDOUT_SEEDS)[:len(seeds)]
    for a in doc["attempts"]:
        assert {"seed", "freeze_commit", "rules_sha256", "approach", "passed", "slices"} <= set(a)


def test_a_malformed_attempts_file_exits_2(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    (tmp_path / "attempts.json").write_text("[1, 2")
    code, _, err = w.run(capsys)
    assert code == 2 and "not a held-out attempts file" in err


def test_thresholds_record_reads_one_seeds_section():
    text = ("# T\n\n## Attempt 1: seed 29\nFreeze commit: `abc1234`\nrules_sha256: `" + "b" * 64 + "`\n"
            "Approach family: persistence rule\n\nrationale\n\n## Attempt 2: seed 31\nFreeze commit: `def5678`\n")
    assert check.thresholds_record(29, text) == {"freeze_commit": "abc1234", "rules_sha256": "b" * 64,
                                                 "approach": "persistence rule"}
    assert check.thresholds_record(31, text) == {"freeze_commit": "def5678"}
    assert check.thresholds_record(37, text) == {}


def test_b3_thresholds_record_reads_the_detection_hash_of_the_seeds_own_freeze():
    text = ("## Attempt 1: seed 29\nFreeze commit: `abc1234`\nrules_sha256: `" + "b" * 64 + "`\ndetection_sha256: `" + "c" * 64
            + "`\n\n## Score\n\ndetection_sha256: `" + "d" * 64 + "`\n")
    assert check.thresholds_record(29, text) == {"freeze_commit": "abc1234", "rules_sha256": "b" * 64,
                                                 "detection_sha256": "c" * 64}      # not the one under Score


def test_the_committed_thresholds_record_exactly_the_scored_attempts():
    """Every scored seed has its record, and the only record without a score is the next unused seed's: a freeze
    record is written before its seed is generated and scored (calibration.md, AC-T02)."""
    text = (ROOT / "docs/thresholds.md").read_text()
    assert "<!-- attempts:begin -->" in text
    scored = {a["seed"] for a in json.loads(check.ATTEMPTS.read_text())["attempts"]}
    recorded = {s for s in check.HELDOUT_SEEDS if check.thresholds_record(s, text)}
    pending = recorded - scored
    nxt = next((s for s in check.HELDOUT_SEEDS if s not in scored), None)
    assert scored <= recorded and pending <= {nxt}


# ----------------------------------------------------------------- AC-K-NFR-01
def test_nfr_the_real_pipeline_runs_offline_with_sockets_blocked(tmp_path, monkeypatch, capsys):
    """AC-NFR-001 and AC-K-NFR-01 (offline; the full make check-5 measures about 8 s on this host, the
    bound is 10 minutes): real analyse on one seed 5 cell, used as both sets (relabelled 29 here, in a
    temp dir only)."""
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    # the nine base takes of the cell; the four foot-fault takes (09 to 12) need the foot side files, which this
    # temp dir does not hold (the labels' foot paths are dropped for the same reason)
    cell_takes = [t for t in labels["takes"] if t["take_id"].startswith("exercise_front_good_")
                  and t["take_id"].split("_")[3] < "09"]
    assert len(cell_takes) == 9
    shutil.copy(ROOT / "fixtures/input/expected/exercise/animation.json", tmp_path / "exp.json")
    for t in cell_takes:
        shutil.copy(ROOT / t["follower"], tmp_path / f"{t['take_id']}.json")
        t["expected"], t["follower"] = "exp.json", f"{t['take_id']}.json"
        del t["expected_feet"], t["follower_feet"]
    for name, seed in (("heldout", 29), ("followers", 5)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "labels.json").write_text(json.dumps({**labels, "seed": seed, "takes": cell_takes}))
    for attr, path in (("ROOT", tmp_path), ("HELDOUT", tmp_path / "heldout"), ("TUNING", tmp_path / "followers"),
                       ("ATTEMPTS", tmp_path / "none.json"), ("THRESHOLDS_DOC", tmp_path / "thresholds.md"),
                       ("OUT_DIR", tmp_path / "out"), ("SCORE_RECORD", tmp_path / "score-heldout.json")):
        monkeypatch.setattr(check, attr, path)
    (tmp_path / "score-heldout.json").write_text(json.dumps(shipped_score_record()))
    (tmp_path / "thresholds.md").write_text(freeze_section(29))

    def no_network(*a, **k):
        raise AssertionError("check-5 opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    started = time.time()
    code = check.main([])
    out, _ = capsys.readouterr()
    doc = json.loads(out)
    assert code in (0, 1) and time.time() - started < 600
    assert errors_of(doc) == [] and doc["gate"]["metrics"]["slices"]["good/front"]["takes"] == 9


# ----------------------------------------------------------------- the foot side files (TICKET-040)
# A take whose labels name expected_feet and follower_feet is analysed with them, through score_report.feet_kwargs.
def feet_take(root, **names):
    for name in ("e.json", "f.json", "ef.json", "ff.json"):
        (root / name).write_text("{}")
    return {"take_id": "t0", "expected": "e.json", "follower": "f.json", **names}


def recorder(monkeypatch):
    """Swap `check.analyse` for a recorder of the foot options it is given."""
    seen = []
    monkeypatch.setattr(check, "analyse", lambda e, f, **feet: seen.append(feet) or {"faults": []})
    return seen


def test_a_take_that_names_foot_files_is_analysed_with_them(tmp_path, monkeypatch):
    seen = recorder(monkeypatch)
    take = feet_take(tmp_path, expected_feet="ef.json", follower_feet="ff.json")
    analyses, errors = check.analyse_set({"takes": [take]}, tmp_path)
    assert errors == [] and list(analyses) == ["t0"]
    assert seen == [{"expected_feet": str(tmp_path / "ef.json"), "follower_feet": str(tmp_path / "ff.json")}]


def test_a_take_without_foot_files_is_analysed_as_it_always_was(tmp_path, monkeypatch):
    seen = recorder(monkeypatch)
    analyses, errors = check.analyse_set({"takes": [feet_take(tmp_path)]}, tmp_path)
    assert errors == [] and seen == [{}]


def test_the_check_and_the_real_report_pick_the_same_foot_files_for_the_same_labels(tmp_path, monkeypatch):
    """One way to turn a take's names into `pipeline.run` options: `score_report.feet_kwargs`."""
    from part5 import real
    seen = recorder(monkeypatch)
    take = feet_take(tmp_path, expected_feet="ef.json", follower_feet="ff.json")
    check.analyse_set({"takes": [take]}, tmp_path)
    assert real._feet_names(tmp_path, "e.json", "f.json", take) == {"expected_feet": "ef.json", "follower_feet": "ff.json"}
    assert check.feet_kwargs(real._feet_names(tmp_path, "e.json", "f.json", take), tmp_path) == seen[0]


def test_a_named_foot_file_that_is_missing_is_an_error_naming_the_take(tmp_path, monkeypatch):
    recorder(monkeypatch)
    take = feet_take(tmp_path, expected_feet="ef.json", follower_feet="gone.json")
    analyses, errors = check.analyse_set({"takes": [take]}, tmp_path)
    assert analyses == {} and errors == ["check-5: t0: gone.json not found"]


def test_the_committed_tuning_set_names_a_foot_file_pair_for_every_take():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    assert len(labels["takes"]) == 156
    assert all((ROOT / t["expected_feet"]).is_file() and (ROOT / t["follower_feet"]).is_file() for t in labels["takes"])


# ----------------------------------------------------------------- profiles (ADR-0016, AC-PROF-13)
def test_check_reports_profiles_sha256(tmp_path, monkeypatch, capsys):
    code, out, err = world(tmp_path, monkeypatch).run(capsys)
    doc = json.loads(out)
    assert code == 0 and doc["profiles_sha256"] == profiles.file_sha256() == check.profiles_hash()
    assert list(doc)[-3:] == ["rules_sha256", "detection_sha256", "profiles_sha256"] and errors_of(doc) == []
    assert doc["rules_sha256"] == RULES_SHA and doc["detection_sha256"] == check.detection_hash()


def test_check_numbers_unchanged_by_profiles(tmp_path, monkeypatch, capsys):
    """The profiles file is information: another file changes `profiles_sha256` and nothing else in the document, and
    `part5/rules.json` is not touched by profiles (check-5 runs fitness only)."""
    w = world(tmp_path, monkeypatch)
    code, out, _ = w.run(capsys)
    first = json.loads(out)
    other = json.loads(profiles.PROFILES_PATH.read_text())
    other["profiles"]["dance"]["kinds"]["position"]["threshold_multiplier"] = 3.0
    (tmp_path / "other-profiles.json").write_text(json.dumps(other))
    monkeypatch.setattr(profiles, "PROFILES_PATH", tmp_path / "other-profiles.json")
    code_b, out_b, _ = w.run(capsys)
    second = json.loads(out_b)
    assert code == code_b == 0 and second["profiles_sha256"] != first["profiles_sha256"]
    assert {k: v for k, v in second.items() if k != "profiles_sha256"} == \
           {k: v for k, v in first.items() if k != "profiles_sha256"}
    assert first["rules_sha256"] == RULES_SHA


def test_check_exits_2_when_the_profiles_file_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(profiles, "PROFILES_PATH", tmp_path / "gone.json")
    code, out, err = world(tmp_path, monkeypatch).run(capsys)
    assert code == 2 and out == "" and "gone.json not found" in err
