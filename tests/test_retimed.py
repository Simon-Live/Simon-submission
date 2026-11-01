"""The retimed seed 5 takes and the keys they bound (recheck N2, stakeholder-proxy ruling; docs/specs/rep-persistence.md).

The 27 good-light seed 5 exercise takes 00 to 08 (24 planted faults) are retimed into six rows with `tests/retimed.py`:
15, 10 and 5 fps at normal speed, a 2 s and a 1.5 s squat at 30 fps, a 1.5 s squat at 15 fps. The ruling: the body floor
is chosen inside the values that keep every row at attempt 3's 24 of 24 faults found. This file pins that at the shipped
rules, pins the tops of the sweep (`part5.sweep.RETIMED_TOPS`) by showing the value above each loses a fault, and checks
the generator. Only seed 5 is read; nothing is data: the clips are written into a temporary directory.
"""
import json
from pathlib import Path

import pytest
import retimed

from part5 import sweep
from part5.detect import load_rules

WORKERS = 8
ROWS = {"15fps_x1": 46, "10fps_x1": 31, "5fps_x1": 16, "30fps_x1.5": 61, "30fps_x2": 46, "15fps_x2": 23}   # example frames
# The row where the value above each top loses a fault (scripts/retimed_floor.py KEY prints every row).
ABOVE_THE_TOP = {"min_frames_floor_body": ("30fps_x2", 24), "upper_arm_out threshold_deg": ("5fps_x1", 12),
                 "min_fraction": ("5fps_x1", 0.43)}


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    return retimed.write_variants(tmp_path_factory.mktemp("retimed"))


def rules_at(key, value):
    rules = load_rules()
    param = next(p for p in sweep.params(rules, capped=False) if p.name == key)
    return sweep.with_value(rules, param.path, value)


def test_the_generator_writes_six_rows_of_27_pairs_with_24_planted_faults_each(index):
    rows = {}
    for entry in index:
        rows.setdefault(entry["variant"], []).append(entry)
    assert {row: entries[0]["n_exp"] for row, entries in rows.items()} == ROWS
    assert all(len(entries) == 27 for entries in rows.values())
    assert all(sum(len(e["faults"]) for e in entries) == retimed.LABELLED == 24 for entries in rows.values())
    assert sum(e["correct"] for e in rows["15fps_x1"]) == 6        # two correct takes at each of three angles


def test_the_generator_plays_the_clip_faster_and_samples_it_at_the_new_rate(index):
    base = json.loads((retimed.ROOT / retimed.picked_takes()[0]["expected"]).read_text())
    fast = json.loads(Path(next(e for e in index if e["variant"] == "30fps_x2")["expected"]).read_text())
    assert (base["duration_s"], base["frame_count"]) == (3.0, 91)
    assert (fast["fps"], fast["frame_count"], len(fast["frames"]), fast["duration_s"]) == (30, 46, 46, 1.5)   # 3 s played twice as fast
    assert fast["frames"][-1]["joints"]["nose"] == pytest.approx(base["frames"][-1]["joints"]["nose"], abs=1e-6)
    slow = json.loads(Path(next(e for e in index if e["variant"] == "5fps_x1")["expected"]).read_text())
    assert (slow["fps"], slow["frame_count"], slow["duration_s"]) == (5, 16, 3.0)                          # the same 3 s, 5 per second


def test_the_generator_reads_seed_5_only():
    with pytest.raises(ValueError, match="seed 5 only"):
        retimed.picked_takes({"seed": 37, "takes": []})


def test_n2_the_shipped_rules_keep_every_retimed_row_at_24_of_24(index):
    """The pin of the ruling: attempt 3 found 24 of 24 in every row; the split floor (and every swept key) must too."""
    rows = retimed.tally(index, workers=WORKERS)
    assert {row: (r["tp"], r["labels"]) for row, r in rows.items()} == {row: (24, 24) for row in ROWS}
    assert all(r["foc"] == 0 for r in rows.values())               # and no correct take is given a fault


def test_n2_the_body_floor_top_keeps_every_row_and_the_value_above_it_loses_a_fault(index):
    """The qualifying range of the body floor ends at 20 on the step-4 grid. At the top every row still finds 24; at 24
    the 1.5 s squat at 30 fps loses one (the next test)."""
    top = sweep.RETIMED_TOPS["min_frames_floor_body"]
    at_top = retimed.tally(index, rules_at("min_frames_floor_body", top), WORKERS)
    assert all((r["tp"], r["labels"]) == (24, 24) for r in at_top.values()), at_top
    assert top < load_rules()["default"]["min_frames_floor"]          # the body floor is not the foot floor's 32


@pytest.mark.parametrize("key", sorted(ABOVE_THE_TOP))
def test_n2_the_value_above_each_top_loses_a_fault_in_its_row(index, key):
    row, above = ABOVE_THE_TOP[key]
    entries = [e for e in index if e["variant"] == row]
    assert len(entries) == 27
    assert retimed.tally(entries, rules_at(key, above), WORKERS)[row]["tp"] < 24
    top = sweep.RETIMED_TOPS[key]
    assert retimed.tally(entries, rules_at(key, top), WORKERS)[row]["tp"] == 24


def test_n2_the_sweep_never_goes_above_a_top():
    rules = load_rules()
    capped = {p.name: p.high for p in sweep.params(rules)}
    assert {name: capped[name] for name in sweep.RETIMED_TOPS} == sweep.RETIMED_TOPS
    free = {p.name: p.high for p in sweep.params(rules, capped=False)}
    assert all(free[name] > top for name, top in sweep.RETIMED_TOPS.items())
    assert [p.name for p in sweep.params(rules, only={"min_frames_floor_body"})] == ["min_frames_floor_body"]


def test_n2_the_shipped_values_are_inside_their_tops():
    rules = load_rules()
    assert rules["default"]["min_frames_floor_body"] <= sweep.RETIMED_TOPS["min_frames_floor_body"]
    assert rules["measures"]["upper_arm_out"]["threshold_deg"] <= sweep.RETIMED_TOPS["upper_arm_out threshold_deg"]
    assert rules["default"]["min_fraction"] <= sweep.RETIMED_TOPS["min_fraction"]
    assert rules["default"]["min_frames_floor"] == 32          # the foot floor is held by the ruling, not swept
    assert "min_frames_floor" not in {p.name for p in sweep.params(rules)}
