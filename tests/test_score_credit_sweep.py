"""TICKET-078 (review B3): `score.credit` through the whole pipeline, on the score's own sweep takes.

The acceptance asks for a sweep where credit never rises as a fault grows. tests/test_score_credit_pins.py proves it with the
alignment held fixed, measure by measure. This file runs the real pipeline over `score_report.run_sweep`'s takes (one fault
type at growing size on an otherwise fixed take, `random.Random(1234)`, so it is deterministic) and pins what was measured:

- the credit falls from the take with no fault to the largest fault, at every level, in percent and in points;
- foot out and arms wider never raise it, at any step; the trunk lean sweep raises it at two steps, by 0.1 and 0.2 of a
  percent (4 to 20 points, pinned in the same loop, so a rise of points too small to move the percent would show), and at
  each of those steps the alignment moved (`alignment.exp_to_fol` differs from the step before): the take is aligned to the
  example again each time, a few frames land elsewhere, and the credit follows them;
- `max_points` is the example's and does not move with the fault (it did before the credit counted the example's seconds).

Strict monotonicity through the pipeline would need the alignment path to change, which is not part of this work and is a
ruling of its own. The rises are recorded in ADR-0020 and docs/specs/score-credit.md."""
from pathlib import Path

import numpy as np
import pytest

from part5.pipeline import run
from part5.score import CREDIT_LEVELS
from part5.score_report import EXERCISE_EXPECTED, run_sweep, score_block

LEVELS = tuple(CREDIT_LEVELS)
# The measured rises of percent and of points: (sweep, size before, size after, level) -> by how much. Nothing else rises, in
# either, and the points rise at exactly the steps the percent does (a rise of points too small to move the percent by 0.1
# would show in POINT_RISES).
RISES = {("trunk_lean center", 20, 25, "hard"): 0.1, ("trunk_lean center", 25, 30, "normal"): 0.1,
         ("trunk_lean center", 25, 30, "hard"): 0.2}
POINT_RISES = {("trunk_lean center", 20, 25, "hard"): 12, ("trunk_lean center", 25, 30, "normal"): 4,
               ("trunk_lean center", 25, 30, "hard"): 20}


@pytest.fixture(scope="module")
def sweeps(tmp_path_factory):
    """{sweep name: [(size, score.credit, exp_to_fol)]} for the three sweeps of the score report."""
    taken = {}

    def analyse_fn(expected, follower):
        result = run({"path": expected}, {"path": follower, "take_id": Path(follower).stem}, score=score_block)
        taken[Path(follower).stem] = (result.analysis["score"]["credit"], np.asarray(result.alignment.exp_to_fol).copy())
        return result.analysis

    assert Path(EXERCISE_EXPECTED).is_file()
    found = run_sweep(tmp_path_factory.mktemp("credit-sweep"), analyse_fn=analyse_fn)
    return {name: [(size, *taken[f"{name.split()[0]}_{size}"]) for size, _ in points] for name, points in found.items()}


def percent(credit, level):
    return credit["levels"][level]["percent"]


def test_the_sweep_has_the_three_fault_types_each_from_no_fault_to_the_largest(sweeps):
    assert list(sweeps) == ["foot_out right", "arms_wider both", "trunk_lean center"]
    assert [[size for size, _, _ in takes] for takes in sweeps.values()] == [
        [0, 4, 8, 12, 16, 20, 24, 28], [0, 5, 10, 15, 20, 25, 30, 35], [0, 5, 10, 15, 20, 25, 30]]


def test_max_points_is_the_examples_and_does_not_move_with_the_fault(sweeps):
    maxima = {credit["max_points"] for takes in sweeps.values() for _, credit, _ in takes}
    assert len(maxima) == 1 and maxima.pop() > 0
    for takes in sweeps.values():
        assert len({credit["levels"][level]["max_points"] for _, credit, _ in takes for level in LEVELS}) == 3


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("name", ["foot_out right", "arms_wider both", "trunk_lean center"])
def test_credit_falls_from_the_take_with_no_fault_to_the_largest_fault(sweeps, name, level):
    takes = sweeps[name]
    first, last = takes[0][1]["levels"][level], takes[-1][1]["levels"][level]
    assert last["percent"] < first["percent"] and last["points"] < first["points"]


def test_through_the_pipeline_credit_rises_only_at_the_measured_steps_and_only_where_the_alignment_moved(sweeps):
    rises, point_rises = {}, {}
    for name, takes in sweeps.items():
        for (before, was, was_aligned), (after, now, now_aligned) in zip(takes, takes[1:]):
            for level in LEVELS:
                key = (name, before, after, level)
                step = round(percent(now, level) - percent(was, level), 1)
                gained = now["levels"][level]["points"] - was["levels"][level]["points"]
                if step > 0:
                    rises[key] = step
                if gained > 0:
                    point_rises[key] = gained
                if step > 0 or gained > 0:
                    assert not np.array_equal(was_aligned, now_aligned), key
    assert rises == pytest.approx(RISES)
    assert point_rises == POINT_RISES
    assert max(rises.values()) == 0.2 and not [key for key in rises if key[3] == "easy" or key[0] != "trunk_lean center"]
