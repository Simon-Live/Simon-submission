"""part2.trackers.parity (AC-R10): label-free comparison of two tracks.json files on hand-made pairs."""
import json

import numpy as np

from part2.track import mask_to_rle
from part2.trackers import parity

H, W = 8, 30
SLOTS = {0: (0, 8), 1: (10, 18), 2: (20, 28)}  # x ranges of three people


def person(pid, slot):
    m = np.zeros((H, W), dtype=np.uint8)
    x0, x1 = SLOTS[slot]
    m[1:7, x0:x1] = 1
    return {"id": pid, "bbox": [x0, 1, x1 - x0, 6], "mask_rle": mask_to_rle(m), "confidence": 0.9}


def doc(n=100, ids=(0, 1), absent=None, rename=None):
    """ids[i] stands in slot i; absent = {id: set of frames where it is missing}; rename maps id -> written id."""
    absent, rename = absent or {}, rename or {}
    frames = []
    for f in range(n):
        people = [person(rename.get(pid, pid), slot) for slot, pid in enumerate(ids) if f not in absent.get(pid, ())]
        frames.append({"frame": f, "people": people})
    return {"frames": frames}


def test_identical_files_pass():
    r = parity.compare(doc(), doc())
    assert r["pass"] and r["ids_a"] == r["ids_b"] == 2 and r["max_diff_pp"] == 0
    assert all(p["mean_mask_iou"] == 1.0 for p in r["pairs"])


def test_ids_are_matched_by_mask_not_by_number():
    r = parity.compare(doc(), doc(rename={0: 5, 1: 3}))
    assert r["pass"] and {(p["a"], p["b"]) for p in r["pairs"]} == {(0, 5), (1, 3)}


def test_coverage_within_one_point_passes_and_beyond_fails():
    assert parity.compare(doc(), doc(absent={1: {50}}))["pass"]  # 1 frame of 100 = 1 point
    r = parity.compare(doc(), doc(absent={1: {50, 51}}))
    assert not r["pass"] and r["max_diff_pp"] == 2.0 and "coverage" in r["reasons"][0]


def test_different_id_counts_fail():
    r = parity.compare(doc(ids=(0, 1, 2)), doc())
    assert not r["pass"] and r["unmatched_a"] == [2]
    assert any("id counts differ: 3 against 2" == x for x in r["reasons"])


def test_same_count_but_different_people_fail():
    a, b = doc(ids=(0, 1)), doc(ids=(0, 1))
    for f in b["frames"]:  # b's id 1 stands in slot 2 instead of slot 1
        f["people"][1] = person(1, 2)
    r = parity.compare(a, b)
    assert not r["pass"] and r["unmatched_a"] == [1] and r["unmatched_b"] == [1]


def test_different_frames_fail():
    r = parity.compare(doc(n=10), doc(n=9))
    assert not r["pass"] and "different frames" in r["reasons"][0]


def test_cli_exit_codes_and_out_file(tmp_path, capsys):
    a, b, c = tmp_path / "a.json", tmp_path / "b.json", tmp_path / "c.json"
    a.write_text(json.dumps(doc()))
    b.write_text(json.dumps(doc(rename={0: 1, 1: 0})))
    c.write_text(json.dumps(doc(ids=(0,))))
    assert parity.main([str(a), str(b), "--out", str(tmp_path / "r" / "p.json")]) == 0
    assert json.loads((tmp_path / "r" / "p.json").read_text())["pass"] is True
    assert parity.main([str(a), str(c)]) == 1
    assert '"pass": false' in capsys.readouterr().out
