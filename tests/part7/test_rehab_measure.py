"""The Part 5 seam of the progress sheet: reps, peak angle and tempo of one take (docs/specs/progress-sheet.md, TICKET-283)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from part7 import rehab_measure as rm

ROOT = Path(__file__).resolve().parents[2]
REPLAY = json.loads((ROOT / "fixtures" / "input" / "replay.json").read_text())
REAL = json.loads((ROOT / "tests" / "part7" / "fixtures" / "analysis" / "real-part5-1.9.0-es-live.analysis.json").read_text())
GOLDEN = json.loads((ROOT / "tests" / "part7" / "fixtures" / "progress" / "part5-measures-golden.json").read_text())


def test_every_angle_matches_part5_measures_on_a_real_replay() -> None:
    frames = rm.frames_of(REPLAY)[:: GOLDEN["step"]]
    assert set(GOLDEN["measures"]) == set(rm.ALL_NAMES)
    for name, want in GOLDEN["measures"].items():
        got = rm.series(frames, name)
        assert len(got) == len(want)
        for a, b in zip(got, want):
            assert (a is None) == (b is None) and (a is None or abs(a - b) < 1e-3), name


def _leg(angle_deg: float) -> dict[str, tuple[float, float, float] | None]:
    """A left leg from the side: thigh straight down, shin bent `angle_deg` backward at the knee."""
    import math
    shin = (0.0, -0.4 * math.cos(math.radians(angle_deg)), -0.4 * math.sin(math.radians(angle_deg)))
    return {"left_hip": (0.0, 1.0, 0.0), "left_knee": (0.0, 0.6, 0.0), "left_ankle": (shin[0], 0.6 + shin[1], shin[2])}


@pytest.mark.parametrize("bend", [0.0, 45.0, 90.0, 120.0])
def test_knee_bend_is_zero_straight_and_grows_with_the_bend(bend: float) -> None:
    assert rm.value(_leg(bend), "left_knee_flexion") == pytest.approx(bend, abs=1e-6)


def test_an_unseen_joint_gives_no_value_and_a_peak_ignores_one_wild_frame() -> None:
    assert rm.value({"left_hip": (0, 1, 0), "left_knee": None, "left_ankle": (0, 0, 0)}, "left_knee_flexion") is None
    assert rm.peak([10.0, 12.0, 90.0, 13.0, 14.0, None, 15.0]) == (15.0, 6)  # one 90 among 12s and 13s is not the peak
    assert rm.peak([None, None]) is None and rm.peak([]) is None


def test_reps_and_tempo_come_from_the_real_analysis() -> None:
    assert rm.reps(REAL) == 5 and rm.tempo(REAL) == 2.51
    assert rm.reps({}) is None and rm.tempo({}) is None
    no_ref = {"diagnostics": {"guard": {"reps": [{"timing_corr": 0.9}, {"timing_corr": 0.8}]}}}
    assert rm.reps(no_ref) == 2


def test_the_primary_measure_is_declared_then_part5_reps_then_the_trainer_range() -> None:
    assert rm.primary(REAL, REPLAY, "left_knee_flexion") == ("left_knee_flexion", "declared")
    assert rm.primary(REAL, REPLAY, "not_a_measure") == ("left_upper_arm_forward", "part5_reps")
    measure, why = rm.primary({}, REPLAY)
    assert why == "trainer_range" and measure == "right_knee_flexion"  # a squat: the knee moves most
    assert rm.primary({}, {}) == (None, "none")


def test_take_facts_keep_every_peak_and_name_their_source() -> None:
    facts = rm.take_facts(REAL, REPLAY, "right_knee_flexion")
    assert facts["measure"] == "right_knee_flexion" and facts["peak_deg"] == facts["peaks"]["right_knee_flexion"] == 112.7
    assert facts["reps"] == 5 and facts["tempo_ratio"] == 2.51 and facts["source"] == rm.SOURCE == "part7-adapter"
    assert set(facts["peaks"]) == set(rm.ALL_NAMES)
    empty = rm.take_facts(REAL, None)
    assert empty["peak_deg"] is None and empty["peaks"] == {} and empty["reps"] == 5


def test_the_skeleton_is_joints_only_at_ten_frames_a_second() -> None:
    skel = rm.skeleton(REPLAY)
    assert skel is not None and set(skel) == {"joints", "bones", "t", "frames"}
    assert len(skel["frames"]) == len(skel["t"]) <= rm.MAX_FRAMES and skel["t"][0] == 0.0
    gaps = [b - a for a, b in zip(skel["t"], skel["t"][1:])]
    assert max(gaps) <= 4 / 30 + 0.002 and 0.09 <= sum(gaps) / len(gaps) <= 0.11  # 30 fps picked down to about 10
    assert len(skel["frames"][0]) == len(REPLAY["joints"]) and rm.skeleton({"joints": []}) is None


def test_the_error_is_not_yet_validated() -> None:
    assert rm.ERROR_DEG is None and rm.ERROR_SOURCE == "not yet validated"  # AC-4: no in-repo rehab dataset run yet
