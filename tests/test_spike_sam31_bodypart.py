"""Spec: docs/specs/spike-sam31-bodypart.md (AC-001 to AC-005)."""
import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("sam31_bodypart", ROOT / "tools/spikes/sam31_bodypart.py")
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)

K = [[100.0, 0, 50.0], [0, 100.0, 50.0], [0, 0, 1.0]]
KP = {"right_ankle": [0.0, 0.2, 1.0], "right_knee": [0.0, -0.2, 1.0],
      "right_hip": [0.0, -0.6, 1.0]}


def test_parse_prompt_ok_and_errors():  # AC-001
    assert sb.parse_prompt("right foot") == ("right", "foot")
    for bad in ("up foot", "right toe", "foot", ""):
        with pytest.raises(ValueError, match="prompt"):
            sb.parse_prompt(bad)


def test_joint_box_single_joint_clipped_and_missing():  # AC-002
    box = sb.joint_box(KP, K, "right", "foot", (200, 200))
    # ankle at (50, 70), knee at (50, 30): half = 0.4 * 40 = 16
    assert box == [34.0, 54.0, 66.0, 86.0]
    assert sb.joint_box(KP, K, "right", "foot", (60, 60)) == [34.0, 54.0, 60.0, 60.0]
    assert sb.joint_box(KP, K, "left", "foot", (200, 200)) is None
    leg = sb.joint_box(KP, K, "right", "leg", (200, 200))
    assert leg[1] < 30 and leg[3] > 70  # spans hip to ankle, padded


def test_mask_stats():  # AC-003
    m = np.zeros((10, 10), dtype=bool)
    m[2:6, 2:6] = True
    s = sb.mask_stats(m, [2, 2, 6, 6])
    assert s["iou"] == 1.0 and s["inside_box"] == 1.0 and s["mask_px"] == 16
    s = sb.mask_stats(m, [4, 2, 8, 6])
    assert s["inside_box"] == 0.5 and abs(s["iou"] - 8 / 24) < 1e-9
    empty = sb.mask_stats(np.zeros((4, 4), dtype=bool), [0, 0, 2, 2])
    assert empty["iou"] == 0.0 and empty["inside_box"] == 0.0


def test_window_clamps():  # AC-004
    recs = list(range(120))
    assert sb.window(recs, 60) == recs[35:85]
    assert sb.window(recs, 3) == recs[0:50]
    assert sb.window(recs, 118) == recs[70:120]
    assert 60 in sb.window(recs, 60)


def test_decode_rle_round_trip():  # AC-005
    part2 = Path(__file__).resolve().parent.parent / "modules" / "part-2"
    if not (part2 / "part2" / "track.py").exists():
        pytest.skip("Part 2 checkout not present")
    sys.path.insert(0, str(part2))
    from part2.track import mask_to_rle

    m = np.zeros((7, 5), dtype=bool)
    m[1:4, 2:5] = True
    m[6, 0] = True
    assert (sb.decode_rle(mask_to_rle(m)) == m).all()
