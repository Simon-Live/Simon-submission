"""TICKET-078: pins for `score.credit` (`simon.credit.v1`, ADR-0020) that tests/test_score_credit.py leaves open.

Beside the team's tests, never in place of them. What that file states and these do not repeat: the band edges of `credit_of`
and of a single entry at every level, the non-finite skip, the level scaling, 100 points per measure per second at the
`credit_points` call, the half-seen rule, one percent for a take whose measures all sit 0.72 thresholds off, the per-window
list, the null cases, the warning cap and the replay script's numbers.

What is pinned here:

- the band edges through the whole block, not the entry: every measure exactly 0.5, 1 and 2 times its threshold off give a
  take percent of 100, 60 and 20, a hair above each gives the next band, and so at easy and hard (edges scale by the level's
  tolerance);
- 100 points per measure per second in the block, whatever the frame rate, at the three levels' multipliers, and `max_points`
  from the seconds and the measures counted;
- `percent` is the take's points over its max points: two windows of different length weigh by their seconds (so it is not
  the mean of the windows' percents), and in every golden each shown percent reads as its shown points over max points;
- credit never rises as a fault grows: a sweep of one measure's offset, measure by measure, and of all of them together, at
  every level and in every window, and the same for the entry function over a fine z grid; the sign of the offset does not
  matter;
- the score's value, grade and fault_cap never read the credit, and the credit's grade is its own letter on its own scale
  (`grades`, the team's S 95, A 85, B 75, C 65, D 55, E 40, F under 40: a slowed take is 59 F beside a credit of 82.7, a B),
  the credit not reading the reported faults and the cap lowering only the value;
- the validator's shape check (R2) accepts every letter of that scale, S and E included, and the `grades` block;
- the credit constants live outside the frozen `score` section of part5/rules.json, whose hash the block still carries."""
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import score
from part5.check import score_params_hash
from part5.detect import load_rules
from part5.measures import FOOT_MEASURES, MEASURES
from part5.output import OutputError, validate_analysis
from part5.pipeline import run
from part5.score_report import score_block
from retimed import labelled_take, picked_takes, retimed_inputs
from shipped_score import aligned, analysis, degrees_off
from test_score_credit import VALIDATOR

ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules()
LEVELS = tuple(score.CREDIT_LEVELS)
GOLDENS = sorted((ROOT / "fixtures/output").glob("analysis*.example.json"))
HAIR = 1e-6   # a relative hair above or below an edge: far above float noise, far below any band


def _take(offset_by_measure, n=300, fps=30, faults=(), speed=1.0):
    """`score.compute_timeline` of a take of `n` frames whose measures sit the given thresholds off the example. The example
    runs at `fps`; the follower does the same routine `speed` times as fast (0.5: it takes twice the seconds)."""
    example_t = np.arange(n) / fps
    take = aligned(n=n, offset=degrees_off(offset_by_measure, RULES))
    return score.compute_timeline(analysis(faults), take, example_t / speed, RULES, expected_times=example_t)


def _all(offset):
    return {name: offset for name in MEASURES}


def _credit(offset, **kw):
    return _take(_all(offset), **kw)["credit"]


def _non_increasing(series):
    return all(a >= b for a, b in zip(series, series[1:]))


# ---------------------------------------------------------------- the band edges, through the block
EDGES = [(0.0, 100.0), (0.5, 100.0), (0.5 * (1 + HAIR), 60.0), (1.0, 60.0), (1.0 * (1 + HAIR), 20.0), (2.0, 20.0),
         (2.0 * (1 + HAIR), 0.0), (7.0, 0.0)]


@pytest.mark.parametrize("offset,percent", EDGES, ids=lambda v: f"{v:.7g}")
def test_a_take_whose_every_measure_sits_at_a_band_edge_gets_that_bands_percent(offset, percent):
    """0.5, 1 and 2 times the threshold earn credit 1, 0.6 and 0.2 (an edge belongs to its own band); beyond 2, 0."""
    credit = _credit(offset)
    assert credit["percent"] == percent and credit["levels"]["normal"]["percent"] == percent
    assert [w["percent"] for w in credit["per_window"]] == [percent] * len(credit["per_window"])
    assert credit["points"] == pytest.approx(percent / 100 * credit["max_points"], abs=1)


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("edge,inside,outside", [(0.5, 100.0, 60.0), (1.0, 60.0, 20.0), (2.0, 20.0, 0.0)])
def test_the_edges_move_with_the_levels_tolerance_and_each_level_gets_its_own_percent(level, edge, inside, outside):
    """A hair under edge x tolerance is in the band, a hair over it falls to the next, at easy (x1.5), normal and hard (x0.7)."""
    tol = score.CREDIT_LEVELS[level]["tolerance"]
    under, over = _credit(edge * tol * (1 - HAIR)), _credit(edge * tol * (1 + HAIR))
    assert under["levels"][level]["percent"] == inside
    assert over["levels"][level]["percent"] == outside


def test_the_three_levels_of_one_take_read_the_same_measures_through_their_own_bands():
    """Every measure 0.72 thresholds off: 0.72 / 1.5 <= 0.5 (full credit at easy), <= 1 at normal, > 1 at hard."""
    credit = _credit(0.72)
    assert [credit["levels"][level]["percent"] for level in LEVELS] == [100.0, 60.0, 20.0]
    assert (credit["percent"], credit["tolerance"]) == (60.0, "normal")


# ---------------------------------------------------------------- 100 points per measure per second; max_points
@pytest.mark.parametrize("fps", [10, 30, 60])
def test_the_block_counts_100_points_per_measure_per_second_whatever_the_frame_rate(fps):
    """Ten seconds of every measure: max_points is measures x 10 s x 100 x the level's multiplier, points follow the bands."""
    n = 10 * fps   # frames of a 10 s example, two windows of 5 s on the follower's clock
    credit = _credit(0.72, n=n, fps=fps)
    base = len(MEASURES) * 10 * score.POINTS_PER_MEASURE_SECOND
    assert score.POINTS_PER_MEASURE_SECOND == 100 == credit["points_per_measure_second"]
    assert len(credit["per_window"]) == 2
    for level, earned in (("easy", 1.0), ("normal", 0.6), ("hard", 0.2)):
        shown, multiplier = credit["levels"][level], score.CREDIT_LEVELS[level]["multiplier"]
        assert shown["max_points"] == base * multiplier
        assert shown["points"] == pytest.approx(earned * shown["max_points"], rel=1e-9)
    assert [credit["max_points"], credit["points"]] == [credit["levels"]["normal"][k] for k in ("max_points", "points")]


def test_max_points_does_not_depend_on_how_far_the_follower_is_from_the_example():
    near, far = _credit(0.0), _credit(5.0)
    assert near["max_points"] == far["max_points"] > 0 and near["points"] == near["max_points"] and far["points"] == 0


def test_max_points_counts_only_the_measures_seen_in_half_of_a_window():
    n = 300
    seen = aligned(n=n)
    hidden = list(MEASURES)[:2]
    for name in hidden:   # seen in an eighth of the frames: under half of either window, so not counted at all
        seen["follower"][name] = np.where(np.arange(n) < n // 8, 0.0, np.nan)
    full = score.compute_timeline(analysis(), aligned(n=n), np.arange(n) / 30, RULES, expected_times=np.arange(n) / 30)
    some = score.compute_timeline(analysis(), seen, np.arange(n) / 30, RULES, expected_times=np.arange(n) / 30)
    full, some = full["credit"], some["credit"]
    assert some["max_points"] == pytest.approx(full["max_points"] * (len(MEASURES) - len(hidden)) / len(MEASURES), abs=2)
    assert some["percent"] == 100.0


# ---------------------------------------------------------------- the example's clock (review B2)
@pytest.mark.parametrize("speed", [0.5, 1.0, 2.0])
def test_the_same_routine_has_the_same_points_and_max_points_at_half_normal_and_double_speed(speed):
    """The points are counted in the example's seconds, so a follower who takes twice as long, or half, changes neither the
    maximum nor, with the same measures off by the same amount, the points. (On the follower's clock they would double.)"""
    reference, slow_or_fast = _credit(0.72), _credit(0.72, speed=speed)
    for level in LEVELS:
        assert slow_or_fast["levels"][level] == reference["levels"][level]
    assert (slow_or_fast["points"], slow_or_fast["max_points"], slow_or_fast["percent"]) == (
        reference["points"], reference["max_points"], reference["percent"])


def test_with_the_same_z_on_every_example_frame_the_points_are_equal_at_any_speed_and_only_the_windows_t_s_move():
    """The z is constant (every measure 0.4 thresholds off on every frame), so nothing but the clock could change the points,
    and they are equal at half, normal and double speed; only the follower seconds a window is shown at (`t_s`) move. With
    real takes the points also move, in both directions, and the falls were not traced: see the pipeline test at half speed
    below."""
    slow, normal, fast = (_credit(0.4, speed=s) for s in (0.5, 1.0, 2.0))
    assert slow["points"] == normal["points"] == fast["points"] and slow["max_points"] == normal["max_points"]
    assert [w["t_s"][1] for w in slow["per_window"]][-1] > [w["t_s"][1] for w in fast["per_window"]][-1]


def test_a_window_without_the_examples_clock_has_no_credit_rather_than_the_followers_seconds():
    """`compute_timeline` without `expected_times` has no seconds to count: no block, and nothing else of the score moves."""
    n = 300
    take, times = aligned(n=n, offset=degrees_off(_all(0.4), RULES)), np.arange(n) / 30
    bare = score.compute_timeline(analysis(), take, times, RULES)
    timed = score.compute_timeline(analysis(), take, times, RULES, expected_times=times)
    assert bare["credit"] is None and timed["credit"] is not None
    assert [w["value"] for w in bare["timeline"]] == [w["value"] for w in timed["timeline"]] and bare["value"] == timed["value"]


def test_the_example_frame_step_is_first_to_last_time_over_frames_less_one():
    assert score.example_frame_s(np.arange(91) / 30) == pytest.approx(1 / 30)
    assert score.example_frame_s([0.0, 0.5, 1.0]) == 0.5
    for no_clock in ([], [1.0], [2.0, 2.0], [float("nan"), 0.5, 1.0]):
        assert score.example_frame_s(no_clock) is None


def test_a_take_of_zero_frames_or_seconds_has_no_credit_and_no_division_by_zero():
    credit = score.credit_block([{"t_s": (1.0, 1.0), "credit_raw": score.credit_sums(np.zeros((0, 0)), 1 / 30)}])
    assert credit is None


def test_pipeline_takes_at_half_speed_keep_the_maximum_and_their_points_stay_within_bounds_that_refuse_doubling(tmp_path):
    """The 27 good-light, clean seed 5 exercise takes (`retimed.picked_takes`: three angles, two correct and seven faulty per
    angle; the set the retimed floor tests use, and a wider one than the two the review replayed by hand) played at half speed
    (twice the seconds) and run through the whole pipeline against their own example, with the score.

    The points are counted on the example's clock, so the same measures seen mean the same `max_points`, and the points do not
    scale with the follower's clock. They are not equal: they move in both directions, and the falls were not traced further.
    `scripts/make_score_credit_retime_noise.py --speeds 0.5` measured on these 27 takes: the same basis and the same `max_points`
    in all 27, points up in 4 by at most 14 (0.23 percent of the points) and down in 23 by at most 736 (12.7 percent); its
    `--mode stretch`, which keeps the file's own frames with timestamps scaled, falls too. So the bounds below: up by at most
    2 percent, and within 20 percent either way. On the follower's clock the points nearly doubled at half speed
    (exercise_front_good_00_correct, retimed as here: 5525, then 9826, at 7181813), which both bounds refuse."""
    for take in picked_takes():
        expected, slow = retimed_inputs(take, tmp_path / f"{take['take_id']}.slow.json", 0.5)
        original = {"path": str(ROOT / take["follower"]), "take_id": take["take_id"]}
        normal, half = (run(expected, follower, score=score_block).analysis["score"] for follower in (original, slow))
        assert half["basis"] == normal["basis"], take["take_id"]
        assert half["credit"]["max_points"] == normal["credit"]["max_points"] > 0, take["take_id"]
        before, change = normal["credit"]["points"], half["credit"]["points"] - normal["credit"]["points"]
        assert change <= 0.02 * before and abs(change) <= 0.2 * before, (take["take_id"], before, change)


# ---------------------------------------------------------------- percent is points over max_points
def _windows(plan):
    """Windows of a 30 fps take: `plan` is [(first frame, frame count, offset in thresholds)]; each window spans its seconds."""
    n = sum(count for _, count, _ in plan)
    offset = {name: np.concatenate([np.full(count, off) for _, count, off in plan]) for name in MEASURES}
    take = aligned(n=n, offset=degrees_off(offset, RULES))
    p, tempo = score.params_of(RULES), {"weight": 0, "cap": 0, "cues": None}
    out = []
    for first, count, _ in plan:
        span = (first / 30, (first + count) / 30)
        out.append(score.timeline_window(span, analysis(), take, np.arange(first, first + count), RULES, p, tempo, None,
                                         timed=False, frame_s=1 / 30))
    return out


def test_percent_is_the_takes_points_over_its_max_points_so_a_longer_window_weighs_more():
    """2 s held perfectly then 6 s three thresholds off: 100 and 0 per window, 25 for the take (not their mean, 50)."""
    credit = score.timeline_block(_windows([(0, 60, 0.0), (60, 180, 3.0)]), "reps", RULES)["credit"]
    per = len(MEASURES) * score.POINTS_PER_MEASURE_SECOND
    assert [w["percent"] for w in credit["per_window"]] == [100.0, 0.0]
    assert [(w["points"], w["max_points"]) for w in credit["per_window"]] == [(per * 2, per * 2), (0, per * 6)]
    assert (credit["points"], credit["max_points"]) == (per * 2, per * 8)
    assert credit["percent"] == 25.0 == 100 * credit["points"] / credit["max_points"]


def reads_as_points_over_max(entry):
    """`percent` is 100 * points / max_points, to 0.1, where points and max_points are each shown as a whole number."""
    points, top = entry["points"], entry["max_points"]
    low, high = 100 * (points - 0.5) / (top + 0.5), 100 * (points + 0.5) / (top - 0.5)
    return low - 0.05 <= entry["percent"] <= high + 0.05


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.name)
def test_in_every_golden_each_shown_percent_reads_as_its_shown_points_over_max_points(path):
    credit = json.loads(path.read_text())["score"]["credit"]
    for entry in [credit, *credit["levels"].values(), *credit["per_window"]]:
        assert 0 <= entry["points"] <= entry["max_points"] and reads_as_points_over_max(entry), entry
    assert credit["percent"] == credit["levels"]["normal"]["percent"]


# ---------------------------------------------------------------- credit never rises as a fault grows
SWEEP = sorted({i / 10 for i in range(0, 41)} | {edge * (1 + HAIR) for edge in (0.5, 1.0, 2.0)})   # 0 to 4 thresholds


def _series(credit):
    """Every number of a block that a growing fault must not raise: the take's, each level's and each window's."""
    return {"percent": credit["percent"], "points": credit["points"],
            **{f"{level}.{k}": credit["levels"][level][k] for level in LEVELS for k in ("percent", "points")},
            **{f"window{i}.percent": w["percent"] for i, w in enumerate(credit["per_window"])}}


def _sweep(offsets_of):
    rows = [_series(_take(offsets_of(off), n=150)["credit"]) for off in SWEEP]
    return {key: [row[key] for row in rows] for key in rows[0]}


@pytest.mark.parametrize("measure", list(MEASURES))
def test_credit_never_rises_as_one_measures_fault_grows(measure):
    sweep = _sweep(lambda off: {measure: off})
    for key, values in sweep.items():
        assert _non_increasing(values), f"{measure} {key}: {values}"
    assert sweep["percent"][-1] < sweep["percent"][0] == 100.0   # a measure four thresholds off costs its share


def test_credit_never_rises_as_every_measures_fault_grows_and_ends_at_nothing():
    sweep = _sweep(_all)
    for key, values in sweep.items():
        assert _non_increasing(values), f"{key}: {values}"
    assert sweep["percent"][0] == 100.0 and sweep["percent"][-1] == 0.0 and sweep["points"][-1] == 0
    assert sweep["percent"][SWEEP.index(2.0)] == 20.0 and sweep["percent"][SWEEP.index(0.5)] == 100.0


@pytest.mark.parametrize("level", LEVELS)
def test_the_entry_credit_never_rises_as_z_grows(level):
    z = np.linspace(0.0, 6.0, 6001)
    credit = score.credit_of(z, score.CREDIT_LEVELS[level]["tolerance"])
    assert credit[0] == 1.0 and credit[-1] == 0.0 and _non_increasing(credit.tolist())
    assert set(np.unique(credit)) == {0.0, 0.2, 0.6, 1.0}


def test_the_sign_of_the_difference_does_not_matter():
    assert _credit(0.9)["percent"] == _credit(-0.9)["percent"] == 60.0
    assert _series(_credit(-1.7)) == _series(_credit(1.7))


# ---------------------------------------------------------------- reported only
def test_the_credit_does_not_read_the_reported_faults_and_the_cap_lowers_only_the_value():
    """The same movement with no fault and with a small and a large reported fault: one credit, three values."""
    fault = {"measure": "elbow_flexion", "side": "left", "joint": "left_elbow", "magnitude_deg": 30.0, "threshold_deg": 20.0,
             "runs": [[10, 60]], "expected_frames": [10, 60], "coverage": 1.0, "text": "left elbow bent more",
             "follower_t_s": [0.3, 2.0], "at_s": 0.3}
    offset = _all(0.4)
    clean, small, large = (_take(offset, faults=f) for f in ([], [fault], [dict(fault, magnitude_deg=90.0)]))
    assert clean["credit"] == small["credit"] == large["credit"] and clean["credit"]["percent"] == 100.0
    assert clean["value"] > small["value"] >= large["value"]
    assert "fault_cap" not in clean and small["fault_cap"] == large["fault_cap"]


# ---------------------------------------------------------------- the credit's grade is informational (review B1)
def _slowed_correct_take(tmp_path, speed=0.25):
    """The seed 5 correct exercise take played at `speed` (a quarter: four times the seconds), against its example."""
    return retimed_inputs(labelled_take("exercise_front_good_00_correct"), tmp_path / "slowed.json", speed)


def test_the_score_never_reads_the_credit_and_a_slowed_take_is_59_f_beside_a_credit_of_b(tmp_path, monkeypatch):
    """A correct take slowed to a quarter of the speed gets `low_match`: the score is capped at 59, grade F. The credit of what
    was compared is 82.7 percent (measured), a B on the credit's own scale (S 95, A 85, B 75, C 65, D 55, E 40, F under 40; the team's
    8f135ee and 93a95db), so B's band, 75 up to 85, is pinned. Replace the credit block by nothing, and by a block that says 0 and F: no
    other field of the score moves, so value, grade, fault_cap, components and capped_by never read it."""
    expected, follower = _slowed_correct_take(tmp_path)

    def scored():
        return run(expected, follower, score=score_block).analysis

    analysis_ = scored()
    real = analysis_["score"]
    assert [w["code"] for w in analysis_["warnings"]] == ["low_match"]
    assert (real["value"], real["grade"]) == (59, "F") and real["uncapped"]["value"] > 59 and real["capped_by"] == ["low_match"]
    assert score.CREDIT_GRADES[1:3] == [[85, "A"], [75, "B"]]   # B is 75 up to 85 on the credit's own scale
    assert real["credit"]["grade"] == "B" and 75 <= real["credit"]["percent"] < 85   # the warning cap does not reach it
    worst = dict(real["credit"], percent=0.0, grade="F", points=0)
    for replaced in (None, worst):
        monkeypatch.setattr(score, "credit_block", lambda scored_windows, grades=score.CREDIT_GRADES, block=replaced: block)
        other = scored()["score"]
        assert other["credit"] == replaced
        assert {k: v for k, v in other.items() if k != "credit"} == {k: v for k, v in real.items() if k != "credit"}


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.name)
def test_the_credit_grade_is_the_credit_percents_own_letter_whatever_the_score_grade_is(path):
    """The credit's letter is read on the scale the golden carries (`grades`, the credit's own); the score's on its bands."""
    doc = json.loads(path.read_text())["score"]
    assert doc["credit"]["grades"] == score.CREDIT_GRADES
    assert doc["credit"]["grade"] == score.credit_grade(doc["credit"]["percent"], doc["credit"]["grades"])
    assert doc["grade"] == score.grade(doc["value"])


def test_a_committed_golden_shows_two_different_letters_side_by_side():
    letters = {path.name: (json.loads(path.read_text())["score"]["grade"],
                           json.loads(path.read_text())["score"]["credit"]["grade"]) for path in GOLDENS}
    assert any(score_letter != credit_letter for score_letter, credit_letter in letters.values()), letters


# ---------------------------------------------------------------- the validator reads a credit of any shape without raising (R2)
def _golden_with_credit(credit):
    doc = json.loads(GOLDENS[0].read_text())
    doc["score"]["credit"] = credit
    return doc


@pytest.mark.parametrize("credit,message", [
    ("87.5", "score.credit must be an object or null, got str"),
    ([], "score.credit must be an object or null, got list"),
    (12, "score.credit must be an object or null, got int"),
])
def test_a_credit_that_is_not_an_object_or_null_is_refused_not_accepted(credit, message):
    with pytest.raises(OutputError, match=message):
        validate_analysis(_golden_with_credit(credit))


@pytest.mark.parametrize("breaks,message", [
    ({"levels": "normal"}, "levels must be an object whose values are objects"),
    ({"levels": ["easy"]}, "levels must be an object whose values are objects"),
    ({"levels": {"easy": 5}}, "levels must be an object whose values are objects"),
    ({"per_window": {"t_s": [0, 1]}}, "per_window must be a list of objects"),
    ({"per_window": [3]}, "per_window must be a list of objects"),
])
def test_a_credit_with_a_misshapen_levels_or_per_window_fails_with_an_output_error_not_an_attribute_error(breaks, message):
    credit = json.loads(GOLDENS[0].read_text())["score"]["credit"]
    with pytest.raises(OutputError, match=message):
        validate_analysis(_golden_with_credit({**credit, **breaks}))


@pytest.mark.parametrize("mark,letter", score.CREDIT_GRADES)
def test_the_shape_check_and_the_schema_accept_every_letter_of_the_credits_scale_with_its_grades(mark, letter):
    """the team's 8f135ee: the credit's letters run S to F, S and E being credit letters only, with `grades` beside them. Each
    letter at the percent that reaches it, since the validator holds the letter to the percent (review R8 of 1.13.0)."""
    credit = json.loads(GOLDENS[0].read_text())["score"]["credit"]
    doc = _golden_with_credit({**credit, "grade": letter, "percent": float(mark)})
    assert doc["score"]["credit"]["grades"] == score.CREDIT_GRADES
    assert validate_analysis(doc) is doc and not list(VALIDATOR.iter_errors(doc))


@pytest.mark.parametrize("breaks", [{"grade": "G"}, {"grades": [[95, "G"]]}, {"grades": [[95, "S", 1]]}, {"grades": "S"}])
def test_the_schema_refuses_a_letter_off_the_scale_or_a_misshapen_grades(breaks):
    credit = json.loads(GOLDENS[0].read_text())["score"]["credit"]
    assert list(VALIDATOR.iter_errors(_golden_with_credit({**credit, **breaks}))), breaks


@pytest.mark.parametrize("breaks,message", [
    ({"grade": "Z"}, r"score.credit.grade must be one of S, A, B, C, D, E, F, got 'Z'"),
    ({"grade": None}, r"score.credit.grade must be one of S, A, B, C, D, E, F, got None"),
    ({"grades": "S"}, r"score.credit.grades must be \[percent at least, letter\] pairs.*got 'S'"),
    ({"grades": []}, r"score.credit.grades must be \[percent at least, letter\] pairs"),
    ({"grades": [[95, "G"]]}, r"score.credit.grades must be \[percent at least, letter\] pairs"),
    ({"grades": [[95, "S", 1]]}, r"score.credit.grades must be \[percent at least, letter\] pairs"),
    ({"grades": [["95", "S"]]}, r"score.credit.grades must be \[percent at least, letter\] pairs"),
    ({"grades": {"S": 95, "A": 85}}, r"score.credit.grades must be \[percent at least, letter\] pairs"),
    ({"grades": [[85, "A"], [95, "S"]]}, r"score.credit.grades must be .*the percents falling"),          # rising marks
    ({"grades": [[95, "A"], [85, "S"]]}, r"score.credit.grades must be .*in that order"),                 # S after A
    ({"grades": [[95, "S"], [85, "S"]]}, r"score.credit.grades must be .*in that order"),                 # a letter twice
    ({"grade": "S"}, r"score.credit.grade must be the letter score.credit.percent \(66.1\) reaches on score.credit.grades, C, "
                     r"got 'S'"),
    ({"grades": [[95, "S"], [90, "A"], [30, "F"]]}, r"reaches on score.credit.grades, F, got 'C'"),   # 66.1 is an F there
])
def test_the_validator_refuses_a_credit_letter_off_the_scale_or_off_its_percent_and_a_misshapen_grades(breaks, message):
    """Review R8 of 1.13.0: without jsonschema (`part5 doctor`), `grade: "Z"` and `grades: "S"` passed. The validator now holds
    `grade` to the letters S to F and to the letter its percent reaches on `grades`, and `grades` to [percent, letter] pairs
    with the percents falling and the letters in the scale's order."""
    credit = json.loads(GOLDENS[0].read_text())["score"]["credit"]
    assert (credit["percent"], credit["grade"]) == (66.1, "C")   # the double-capped golden
    with pytest.raises(OutputError, match=message):
        validate_analysis(_golden_with_credit({**credit, **breaks}))


def test_the_schema_says_what_part_5s_validator_adds_on_the_credit_grade_and_grades():
    """TICKET-088 N1: a schema-only reader learns the checks the validator adds above the schema's types and enums: grades
    falling, letters in the scale's order with none twice, and the grade the letter its percent reaches on grades."""
    credit = json.loads((ROOT / "contracts/analysis.schema.json").read_text())["properties"]["score"]["properties"]["credit"]
    grade, grades = credit["properties"]["grade"]["description"], credit["properties"]["grades"]["description"]
    assert "Part 5's validator also checks" in grade and "Part 5's validator also checks" in grades
    assert "grade is the letter percent reaches on this document's grades" in grade
    assert "each percent is below the one before" in grades and "the list is not empty" in grades
    assert "the letters run in the scale's order S, A, B, C, D, E, F" in grades and "no letter appears twice" in grades
    assert "never by the alphabet" in grades and "F to S" not in grades


def test_the_validator_reads_the_letter_on_the_documents_own_grades_and_accepts_every_golden():
    credit = json.loads(GOLDENS[0].read_text())["score"]["credit"]
    own = [[95, "S"], [60, "B"], [30, "F"]]   # another scale, well formed: 66.1 is a B on it
    assert validate_analysis(_golden_with_credit({**credit, "grades": own, "grade": "B"}))
    without = {k: v for k, v in credit.items() if k != "grades"}   # none written: the scale every document carries
    assert validate_analysis(_golden_with_credit(without))
    for path in GOLDENS:
        doc = json.loads(path.read_text())
        assert validate_analysis(doc) is doc, path.name


def test_a_document_written_before_1_14_3_keeps_its_own_scale_and_its_letter():
    """TICKET-109 (ADR-0020 Amendment 2): 40.0 to 44.9 is the one band whose letter moved, F on the scale documents carried
    before 1.14.3 and E on the new one. A document validates with the letter its own `grades` give and is refused with the
    other, so an old document stays valid as written and a new one cannot carry the old letter."""
    credit = json.loads(GOLDENS[0].read_text())["score"]["credit"]
    old = [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [45, "E"], [30, "F"]]
    assert credit["grades"] == score.CREDIT_GRADES and score.credit_grade(42.0) == "E"
    assert validate_analysis(_golden_with_credit({**credit, "percent": 42.0, "grades": old, "grade": "F"}))
    assert validate_analysis(_golden_with_credit({**credit, "percent": 42.0, "grade": "E"}))
    with pytest.raises(OutputError, match=r"reaches on score.credit.grades, E, got 'F'"):
        validate_analysis(_golden_with_credit({**credit, "percent": 42.0, "grade": "F"}))
    with pytest.raises(OutputError, match=r"reaches on score.credit.grades, F, got 'E'"):
        validate_analysis(_golden_with_credit({**credit, "percent": 42.0, "grades": old, "grade": "E"}))


def test_a_null_credit_and_a_document_without_one_still_validate():
    doc = json.loads(GOLDENS[0].read_text())
    doc["score"]["credit"] = None
    assert validate_analysis(doc) is doc
    del doc["score"]["credit"]
    assert validate_analysis(doc) is doc


# ---------------------------------------------------------------- the foot measures earn no credit (R5)
def test_the_foot_measures_are_compared_but_earn_no_credit():
    """A take whose foot series sit 90 degrees off the example has the credit of a take without them: `credit_z` reads the
    body measures of MEASURES only, which CONTRACT.md and docs/schemas.md say."""
    n = 150
    plain = aligned(n=n)
    with_feet = aligned(n=n)
    for name in FOOT_MEASURES:
        with_feet["expected"][name], with_feet["follower"][name] = np.zeros(n), np.full(n, 90.0)
    times = np.arange(n) / 30
    credits = [score.compute_timeline(analysis(), take, times, RULES, expected_times=times)["credit"]
               for take in (plain, with_feet)]
    assert credits[0] == credits[1] and credits[0]["percent"] == 100.0
    assert score.credit_z(with_feet, RULES).shape[0] == len(MEASURES) and len(FOOT_MEASURES) > 0
    for doc in ("CONTRACT.md", "docs/schemas.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert "the foot measures (`foot_rotation`, `ankle_inversion`, from the optional foot files) are compared" in text, doc
        assert f"Only the {len(MEASURES)} body measures" in text, doc


# ---------------------------------------------------------------- the constants are outside the frozen score section
def test_the_credit_constants_live_outside_the_frozen_score_section_of_the_rules():
    rules_text = (ROOT / "part5/rules.json").read_text()
    assert "credit" not in rules_text.lower() and "credit" not in json.dumps(RULES.get("score", {})).lower()
    assert score.CREDIT_BANDS == [[0.5, 1.0], [1.0, 0.6], [2.0, 0.2]] and score.CREDIT_VERSION == "simon.credit.v1"
    assert not any("credit" in key for key in score.params_of(RULES))


def test_the_block_still_carries_the_hash_of_the_frozen_score_section_and_the_credit_block_never_changes_it():
    block = _take(_all(0.3))
    assert block["params_sha256"] == score_params_hash()
    assert block["credit"]["version"] == "simon.credit.v1" and block["version"] == score.params_of(RULES)["version"]
