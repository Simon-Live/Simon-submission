"""TICKET-108, AC-CR-12 (ADR-0020 Amendment 1, docs/specs/score-credit.md "The take's last second"): over the example's last
second (at most a third of the frames read), when the follower holds still (every measure's robust range at most half a
threshold), each measure the example moves away in (its range at least one threshold) earns full credit there. A pose both hold,
a movement both make and every measure the example holds are scored as before, `max_points` stays the routine's own, and rep by
rep only the last rep reads the rule. AC-CR-08's one exception is pinned here too.

The regression take is staging take b5acba462f16 (moalborati/simon-part-5-fault-analysis#38): its trainer bends both elbows again in
the last second while the follower holds still (`tests/fixtures/staging-b5acba462f16/`)."""
import copy
import itertools
import json
from pathlib import Path

import numpy as np
import pytest
from shipped_score import analysis, lateral_raise_run

from part5 import score, score_report
from part5.detect import load_rules
from part5.measures import MEASURES
from part5.pipeline import run
from part5.score_report import score_block

ROOT = Path(__file__).resolve().parent.parent
TAKE = ROOT / "tests/fixtures/staging-b5acba462f16"
RULES = load_rules()
FPS, N, TAIL = 30, 150, 30
ELBOW = "left_elbow_flexion"


def thr(name):
    return score.threshold_of(name, RULES)


def base(n=N, moving_to_end=False):
    """Every measure swings 40 degrees once and, unless `moving_to_end`, holds still over the last second."""
    if moving_to_end:
        return 40.0 * np.sin(np.linspace(0.0, 2.0 * np.pi, n))
    return np.concatenate([40.0 * np.sin(np.linspace(0.0, 2.0 * np.pi, n - TAIL)), np.zeros(TAIL)])


def take(exp=None, fol=None, n=N, moving_to_end=False):
    """`aligned` with the example and the follower on the same clock; `exp` and `fol` map a measure to its series."""
    series = base(n, moving_to_end)
    return {"expected": {m: (exp or {}).get(m, series).copy() for m in MEASURES},
            "follower": {m: (fol or {}).get(m, series).copy() for m in MEASURES},
            "exp_to_fol": list(range(n))}


def ramp(series, thresholds, name, n=TAIL):
    """`series` with its last `n` frames ramped away from where they were by `thresholds` of `name`'s threshold."""
    out = np.asarray(series, float).copy()
    out[-n:] += np.linspace(0.0, thresholds * thr(name), n)
    return out


def credit(aligned, n=N):
    t = np.arange(n) / FPS
    return score.compute_timeline(analysis(), aligned, t, RULES, expected_times=t)["credit"]


def rule_off(aligned, rules, frame_s):
    """`credit_tail` that marks nothing: the credit as 1.14.1 gave it, the last second read like any other."""
    return np.zeros((len(MEASURES), np.asarray(aligned["exp_to_fol"]).size), dtype=bool)


@pytest.fixture
def no_rule(monkeypatch):
    monkeypatch.setattr(score, "credit_tail", rule_off)


def marked(full):
    """The expected frames `credit_tail` marks for any measure."""
    return full.any(axis=0).tolist()


# ---------------------------------------------------------------------------------------------- the follower still, the example leaving
def test_the_example_leaving_the_pose_while_the_follower_holds_costs_nothing():
    al = take(exp={m: ramp(base(), 4.0, m) for m in MEASURES})
    full = score.credit_tail(al, RULES, 1 / FPS)
    assert full.shape == (22, N) and full[:, N - TAIL:].all() and not full[:, :N - TAIL].any()
    got, perfect = credit(al), credit(take())
    assert got["percent"] == 100.0 and got["max_points"] == perfect["max_points"] == 22 * 500
    assert all(level["percent"] == 100.0 for level in got["levels"].values())


def test_only_the_measures_the_example_moves_away_in_are_forgiven():
    """The example bends its elbow away while the follower holds still with its upper arm 2.5 thresholds off, a pose both hold:
    the elbow's last second is forgiven and the upper arm's still earns nothing (review B1)."""
    arm = "left_upper_arm_out"
    al = take(exp={ELBOW: ramp(base(), 4.0, ELBOW)},
              fol={arm: base() + np.r_[np.zeros(N - TAIL), np.full(TAIL, 2.5 * thr(arm))]})
    full = score.credit_tail(al, RULES, 1 / FPS)
    assert full[list(MEASURES).index(ELBOW), N - TAIL:].all() and full.sum() == TAIL
    assert credit(al)["percent"] == round(100 * (22 * N - TAIL) / (22 * N), 1)


def test_a_follower_moving_while_the_example_holds_is_scored():
    """A follower who moves on after the example has stopped is left to the alignment's open end, not to this rule."""
    al = take(fol={ELBOW: ramp(base(), 4.0, ELBOW)})
    assert not score.credit_tail(al, RULES, 1 / FPS).any()
    assert credit(al)["percent"] < 100.0


def test_a_nod_does_not_forgive_an_arm_held_wrong():
    """Review B1: both hold eight arm measures 2.5 thresholds off; the follower also nods past a threshold. The follower does not
    hold still, so nothing is forgiven, and the example holds every measure, so nothing would be anyway."""
    arms = [m for m in MEASURES if any(k in m for k in ("elbow", "upper_arm", "forearm"))][:8]
    fol = {m: base() + np.r_[np.zeros(N - TAIL), np.full(TAIL, 2.5 * thr(m))] for m in arms}
    fol["head_forward"] = ramp(base(), 2.0, "head_forward")
    al = take(fol=fol)
    assert not score.credit_tail(al, RULES, 1 / FPS).any()
    assert credit(al)["percent"] < 100.0


def test_without_the_rule_the_same_take_loses_its_last_second(no_rule):
    got = credit(take(exp={m: ramp(base(), 4.0, m) for m in MEASURES}))
    assert got["percent"] < 95.0 and got["max_points"] == 22 * 500


# ---------------------------------------------------------------------------------------------- a real miss still costs
def test_a_held_wrong_pose_in_the_last_second_still_costs():
    """Both hold still; the follower sits 2.5 thresholds off on every measure: nothing earned in the tail, 20 percent lost."""
    al = take(fol={m: base() + np.r_[np.zeros(N - TAIL), np.full(TAIL, 2.5 * thr(m))] for m in MEASURES})
    assert not score.credit_tail(al, RULES, 1 / FPS).any()
    assert credit(al)["percent"] == 80.0


def test_wrong_form_while_both_move_still_costs():
    """The example leaves the pose and the follower follows it, 2.5 thresholds off: both move, so the tail is scored."""
    moving = {m: ramp(base(), 3.0, m) for m in MEASURES}
    al = take(exp=moving, fol={m: moving[m] + np.r_[np.zeros(N - TAIL), np.full(TAIL, 2.5 * thr(m))] for m in MEASURES})
    assert not score.credit_tail(al, RULES, 1 / FPS).any()
    assert credit(al)["percent"] == 80.0


def test_a_follower_who_stops_early_loses_everything_before_the_last_second(monkeypatch):
    """The follower stops 3 s before the end while the example moves on: only the last second is forgiven."""
    moving = base(moving_to_end=True)
    stopped = moving.copy()
    stopped[N - 90:] = moving[N - 90]
    al = take(exp={m: moving for m in MEASURES}, fol={m: stopped for m in MEASURES}, moving_to_end=True)
    full = score.credit_tail(al, RULES, 1 / FPS)
    assert marked(full) == [False] * (N - TAIL) + [True] * TAIL
    c = score.credit_of(score.credit_z(al, RULES))
    c[:, N - TAIL:] = 1.0
    got = credit(al)
    assert got["percent"] == round(100 * float(c.sum()) / c.size, 1) < 100.0
    monkeypatch.setattr(score, "credit_tail", rule_off)
    assert credit(al)["percent"] < got["percent"]


# ---------------------------------------------------------------------------------------------- the edges and the bounds
def step(name, thresholds):
    """The base with a step of `thresholds` of `name`'s threshold in the second half of the tail: a robust range of exactly that."""
    out = base().copy()
    out[N - TAIL // 2:] += thresholds * thr(name)
    return out


@pytest.mark.parametrize("held, left, fires", [(0.5, 1.0, True), (0.0, 1.0, True), (0.6, 1.0, False), (0.0, 0.9, False)])
def test_a_side_holds_at_half_a_threshold_and_leaves_at_one(held, left, fires):
    al = take(exp={ELBOW: step(ELBOW, left)}, fol={ELBOW: step(ELBOW, held)})
    assert bool(score.credit_tail(al, RULES, 1 / FPS).any()) is fires


def test_the_tail_is_never_more_than_a_third_of_a_short_take():
    n = 60
    al = take(n=n, exp={m: ramp(base(n), 4.0, m, n=20) for m in MEASURES})
    assert marked(score.credit_tail(al, RULES, 1 / FPS)) == [False] * 40 + [True] * 20


def test_without_the_example_s_clock_there_is_no_tail():
    al = take(exp={m: ramp(base(), 4.0, m) for m in MEASURES})
    assert not score.credit_tail(al, RULES, None).any()


def test_a_measure_seen_in_under_half_of_the_tail_is_not_read():
    """The example's elbow leaves the pose but is unseen in most of the tail, so nothing moves away that the rule can read."""
    leaving = ramp(base(), 4.0, ELBOW)
    leaving[N - 20:] = np.nan
    assert not score.credit_tail(take(exp={ELBOW: leaving}), RULES, 1 / FPS).any()


# ---------------------------------------------------------------------------------------------- AC-CR-08's one exception
def test_with_the_alignment_fixed_the_credit_rises_only_in_the_last_second_and_only_when_the_follower_stops():
    """The example leaves the pose in its last second; the follower follows that move less and less (`s` of it left out). The
    credit falls while the follower still moves, and rises once, to the full credit of those entries, at the step where the
    follower holds still. Every other frame earns the same at every step, and no step earns more than that full tail."""
    leave = {m: ramp(base(), 3.0, m) for m in MEASURES}
    steps = [round(0.1 * i, 1) for i in range(11)]
    got, fired = [], []
    for s in steps:
        fol = {m: leave[m] - s * (leave[m] - base()) for m in MEASURES}
        al = take(exp=leave, fol=fol)
        fired.append(bool(score.credit_tail(al, RULES, 1 / FPS).any()))
        c = score.credit_of(score.credit_z(al, RULES, score.credit_tail(al, RULES, 1 / FPS)))
        assert (c[:, :N - TAIL] == 1.0).all()   # nothing before the last second moves
        got.append(credit(al)["points"])
    first = fired.index(True)
    assert fired == [False] * first + [True] * (len(steps) - first) and 0 < first < len(steps)
    assert all(a >= b for a, b in itertools.pairwise(got[:first]))   # falls while the follower still moves
    assert got[first:] == [22 * 500] * (len(steps) - first)        # then the last second is earned in full
    assert max(got) <= 22 * 500


# ---------------------------------------------------------------------------------------------- the regression take
@pytest.fixture(scope="module")
def staged():
    return run(str(TAKE / "expected.json"), str(TAKE / "follower.json"), score=score_block).analysis


def test_the_regression_take_reads_91_3_where_1_14_1_read_82_9(staged):
    got = staged["score"]["credit"]
    assert (got["percent"], got["grade"], got["points"], got["max_points"]) == (91.3, "A", 3195, 3500)
    assert {k: v["percent"] for k, v in got["levels"].items()} == {"easy": 96.1, "normal": 91.3, "hard": 83.3}
    assert staged["score"]["value"] == 99 and staged["faults"] == []
    assert staged["diagnostics"]["near_misses"]["total"] == 5   # detection is untouched: the near misses stay


def test_without_the_rule_the_regression_take_reads_what_1_14_1_gave_and_nothing_else_moves(staged, no_rule):
    without = run(str(TAKE / "expected.json"), str(TAKE / "follower.json"), score=score_block).analysis
    got = without["score"]["credit"]
    assert (got["percent"], got["grade"], got["points"], got["max_points"]) == (82.9, "B", 2900, 3500)
    rest = [{**doc, "score": {k: v for k, v in doc["score"].items() if k != "credit"}} for doc in (staged, without)]
    assert rest[0] == rest[1]   # the score, the faults and the near misses do not read the rule


def follower_from_trainer(tmp_path, shift=None):
    """The regression trainer as its own follower; with `shift` (metres, x is the subject's left) the left wrist is moved by it on
    the last second of frames, so the follower follows the movement but with the left forearm off."""
    doc = json.loads((TAKE / "expected.json").read_text())
    out = copy.deepcopy(doc)
    if shift is not None:
        for frame in out["frames"][-TAIL:]:
            frame["joints"]["left_wrist"] = [a + b for a, b in zip(frame["joints"]["left_wrist"], shift)]
    path = tmp_path / ("shifted.json" if shift else "copy.json")
    path.write_text(json.dumps(out))
    return run(str(TAKE / "expected.json"), str(path), score=score_block).analysis


def test_a_real_sustained_miss_in_the_regression_take_s_last_second_still_loses_credit(tmp_path, monkeypatch):
    perfect = follower_from_trainer(tmp_path)["score"]["credit"]
    missed = follower_from_trainer(tmp_path, shift=(0.15, 0.0, 0.0))["score"]["credit"]
    assert missed["percent"] <= perfect["percent"] - 1.0
    monkeypatch.setattr(score, "credit_tail", rule_off)
    assert follower_from_trainer(tmp_path, shift=(0.15, 0.0, 0.0))["score"]["credit"] == missed   # the rule forgave nothing


# ---------------------------------------------------------------------------------------------- rep by rep
def test_rep_by_rep_only_the_last_rep_s_window_reads_the_rule(monkeypatch):
    result = lateral_raise_run()
    assert result.reps and result.reps[-1].ok
    seen = []
    real = score.credit_tail

    def spy(aligned, rules, frame_s):
        seen.append(len(aligned["exp_to_fol"]))
        return real(aligned, rules, frame_s)

    monkeypatch.setattr(score, "credit_tail", spy)
    block = score_report.score_block(result)
    assert block["basis"] == "reps" and seen == [len(result.reps[-1].alignment.exp_to_fol)]
    monkeypatch.setattr(score, "credit_tail", rule_off)
    assert score_report.score_block(result) == block   # the committed lateral raise: the rule forgives nothing there
