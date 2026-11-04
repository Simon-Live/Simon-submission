"""TICKET-047 (R7): score v2 changes the score and nothing detection finds. `fixtures/seed5-detection-baseline.json` holds,
per seed 5 take, the hash of what detection found (status, warnings, faults and near misses without their words), taken
from the detection of attempt 5 and cross-checked against main's code before score v2 (0 of 156 takes differ). The
fitness baseline cannot say this: it hashes the whole analysis, score included, so a score change moves every hash."""
import copy
import json
from pathlib import Path

import pytest

from part5 import profiles_report

ROOT = Path(__file__).resolve().parent.parent
BASELINE = json.loads(profiles_report.DETECTION_BASELINE.read_text())
EXAMPLE = json.loads((ROOT / "fixtures/output/analysis.example.json").read_text())


def test_the_baseline_names_every_seed_5_take_and_the_way_it_was_hashed():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    assert BASELINE["format"] == profiles_report.DETECTION_BASELINE_FORMAT and BASELINE["seed"] == 5
    assert set(BASELINE["takes"]) == {t["take_id"] for t in labels["takes"]} and len(BASELINE["takes"]) == 156
    assert all(len(h) == 64 for h in BASELINE["takes"].values())
    assert "TICKET-047" in BASELINE["_comment"] and "without text" in BASELINE["hashed"]


def test_detection_finds_in_every_seed_5_take_what_it_found_before_score_v2():
    labels = profiles_report.tuning_labels()
    now = profiles_report.detection_baseline_document(labels)["takes"]
    moved = sorted(take_id for take_id, h in BASELINE["takes"].items() if now[take_id] != h)
    assert moved == [], f"detection moved in {len(moved)} take(s): {moved[:5]}"


def test_the_digest_ignores_the_score_the_words_and_the_phrasing():
    base = profiles_report.detection_digest(EXAMPLE)
    other = copy.deepcopy(EXAMPLE)
    other["score"].update(value=3, grade="F", fault_cap=89, uncapped={"value": 99, "grade": "A"}, version="simon.score.v1")
    other["schema_version"] = "1.9.0"
    other["insights"], other["phrasing"] = [], {}
    for fault in other["faults"]:
        fault.update(text="x", text_timed="y", coaching="z", cue="w", cue_kind="range")
    assert profiles_report.detection_digest(other) == base


@pytest.mark.parametrize("change", [
    lambda d: d["faults"][0].update(magnitude_deg=d["faults"][0]["magnitude_deg"] + 0.1),
    lambda d: d["faults"][0].update(runs=[[0, 1]]),
    lambda d: d["faults"].pop(),
    lambda d: d["diagnostics"]["near_misses"]["items"][0].update(frames_over=1),
    lambda d: d["diagnostics"]["near_misses"].update(total=d["diagnostics"]["near_misses"]["total"] + 1),
    lambda d: d.update(warnings=[{"code": "low_match", "text": "x"}]),
    lambda d: d.update(status={"code": "different_movement", "text": "x"}),
])
def test_the_digest_moves_with_a_fault_a_near_miss_a_warning_or_the_status(change):
    other = copy.deepcopy(EXAMPLE)
    change(other)
    assert profiles_report.detection_digest(other) != profiles_report.detection_digest(EXAMPLE)


def test_the_fitness_baseline_comment_names_ticket_047():
    assert "TICKET-047" in json.loads(profiles_report.BASELINE.read_text())["_comment"]


def test_the_writer_refuses_a_set_that_is_not_seed_5(tmp_path, capsys):
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    (tmp_path / "labels.json").write_text(json.dumps({**labels, "seed": 29}))
    assert profiles_report.main(["--set", str(tmp_path), "--write-detection-baseline", "--out", str(tmp_path / "b.json")]) == 2
    assert "tuning set only" in capsys.readouterr().err and not (tmp_path / "b.json").exists()
