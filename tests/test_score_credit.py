"""ADR-0020: `score.credit` (`simon.credit.v1`), the DDR-style credit display, additive beside the score.

Credit per measure and frame by |follower - expected| / threshold over the level's tolerance (<= 0.5: 1.0, <= 1: 0.6,
<= 2: 0.2, else 0; non-finite skipped), 100 points per measure per second, three levels, one `per_window` entry per
compared window of `score.timeline`, null when nothing was compared. Points are counted on the example's clock (review B2 of
TICKET-078). The checks at the bottom restate the formula from the per-frame z the windows saw (a spy on
`score.timeline_window`), which checks the code against its own formula and not against the owner's replay script, and
record what that script printed on the follower's clock, from which the percents differ by under half a point."""
import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5 import score
from part5.contract import golden_run
from part5.detect import load_rules
from part5.measures import MEASURES
from part5.output import OutputError, validate_analysis
from part5.pipeline import run
from part5.score_report import score_block
from shipped_score import aligned, analysis, degrees_off

ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules()
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
GOLDENS = sorted((ROOT / "fixtures/output").glob("analysis*.example.json"))
NAN = float("nan")


# ---------------------------------------------------------------- the credit of one entry
def test_the_bands_give_full_great_good_and_miss_credit_at_their_edges():
    z = np.array([0.0, 0.5, 0.51, 1.0, 1.5, 2.0, 2.01, 9.0])
    assert score.credit_of(z).tolist() == [1.0, 1.0, 0.6, 0.6, 0.2, 0.2, 0.0, 0.0]


EPS = 1e-9


@pytest.mark.parametrize("level", ["easy", "normal", "hard"])
@pytest.mark.parametrize("edge,at,above", [(0.5, 1.0, 0.6), (1.0, 0.6, 0.2), (2.0, 0.2, 0.0)])
def test_each_band_edge_is_inside_its_band_and_just_above_it_falls_to_the_next(level, edge, at, above):
    """z / tolerance exactly 0.5, 1.0 and 2.0 earn the band's credit; a hair above earns the next band's."""
    tol = score.CREDIT_LEVELS[level]["tolerance"]
    on = np.array([edge * tol])
    # the edge itself, computed the way the code divides: pick z so that z / tol is exactly the edge
    assert (on / tol)[0] == edge
    assert score.credit_of(on, tol).tolist() == [at]
    assert score.credit_of(np.array([(edge + EPS) * tol]), tol).tolist() == [above]


def test_a_non_finite_z_is_not_counted():
    c = score.credit_of(np.array([0.0, NAN, np.inf, 3.0]))
    assert c[0] == 1.0 and np.isnan(c[1]) and np.isnan(c[2]) and c[3] == 0.0
    earned, counted = score.credit_sums(np.array([[0.0, NAN, np.inf, 3.0]]), 1 / 30)["levels"]["normal"]
    assert (earned, counted) == (1.0, 2)


def test_a_level_scales_the_thresholds_by_its_tolerance():
    z = np.array([0.7, 0.36, 1.4])
    assert score.credit_of(z, score.CREDIT_LEVELS["easy"]["tolerance"]).tolist() == [1.0, 1.0, 0.6]   # 1.5x looser
    assert score.credit_of(z, score.CREDIT_LEVELS["hard"]["tolerance"]).tolist() == [0.6, 0.6, 0.2]   # 0.7x tighter
    assert score.CREDIT_LEVELS == {"easy": {"tolerance": 1.5, "multiplier": 0.75},
                                   "normal": {"tolerance": 1.0, "multiplier": 1.0},
                                   "hard": {"tolerance": 0.7, "multiplier": 1.5}}


@pytest.mark.parametrize("fps", [10, 30, 60])
def test_points_are_100_per_measure_per_second_whatever_the_frame_rate(fps):
    """Two seconds of one measure held perfectly, a frame lasting 1 / fps on the example's clock: 200 points at normal, times
    0.75 at easy and 1.5 at hard."""
    frames = 2 * fps
    for level, want in (("easy", 150), ("normal", 200), ("hard", 300)):
        pts, poss = score.credit_points(float(frames), frames, 1 / fps, score.CREDIT_LEVELS[level]["multiplier"])
        assert pts == pytest.approx(want) and poss == pytest.approx(want)


def test_a_measure_seen_in_under_half_of_a_window_does_not_count():
    n = 10
    sub = aligned(n=n)
    name, other = list(MEASURES)[:2]
    sub["follower"][name] = np.where(np.arange(n) < 4, 0.0, NAN)    # seen in 4 of 10 frames: left out
    sub["follower"][other] = np.where(np.arange(n) < 5, 0.0, NAN)   # seen in 5 of 10: counted, on its 5 frames
    z = score.credit_z(sub, RULES)
    assert z.shape == (len(MEASURES) - 1, n)
    assert score.credit_sums(z, 1 / 30)["levels"]["normal"][1] == (len(MEASURES) - 2) * n + 5


# ---------------------------------------------------------------- the block of a take
def test_a_take_compared_as_a_whole_carries_one_entry_per_window_and_the_percent_of_its_bands():
    """10 s at 30 fps in two 5 s windows; every measure 0.72 thresholds off (credit 0.6 at normal, 1.0 at easy since
    0.72 / 1.5 < 0.5, 0.2 at hard since 0.72 / 0.7 > 1)."""
    n, fps = 300, 30
    take = aligned(n=n, offset=degrees_off({m: 0.72 for m in MEASURES}, RULES))
    block = score.compute_timeline(analysis(), take, np.arange(n) / fps, RULES, expected_times=np.arange(n) / fps)
    credit = block["credit"]
    assert credit["version"] == "simon.credit.v1" and credit["tolerance"] == "normal"
    assert credit["percent"] == 60.0 and credit["grade"] == "D"
    assert credit["levels"]["easy"]["percent"] == 100.0 and credit["levels"]["hard"]["percent"] == 20.0
    assert credit["bands"] == [[0.5, 1.0], [1.0, 0.6], [2.0, 0.2]] and credit["points_per_measure_second"] == 100
    seconds = n / fps    # every frame lasts 1 / fps on the example's clock
    assert credit["max_points"] == int(score.round_half_up(len(MEASURES) * seconds * 100))
    assert credit["levels"]["hard"]["max_points"] == int(score.round_half_up(len(MEASURES) * seconds * 150))
    assert [w["t_s"] for w in credit["per_window"]] == [w["t_s"] for w in block["timeline"]]
    assert all(w["percent"] == 60.0 for w in credit["per_window"])


def test_per_window_follows_the_compared_windows_of_the_timeline_and_skips_the_others():
    n = 90
    frames = np.arange(n)
    p, tempo = score.params_of(RULES), {"weight": 0, "cap": 0, "cues": None}
    a = score.timeline_window((0.0, 3.0), analysis(), aligned(n=n), frames, RULES, p, tempo, None, timed=False,
                              frame_s=1 / 30)
    far = aligned(n=n, offset=degrees_off({m: 3.0 for m in MEASURES}, RULES))
    b = score.timeline_window((6.0, 9.0), analysis(), far, frames, RULES, p, tempo, None, timed=False, frame_s=1 / 30)
    block = score.timeline_block([a, {"t_s": (3.0, 6.0), "compared": False}, b], "reps", RULES)
    credit = block["credit"]
    assert [w["t_s"] for w in credit["per_window"]] == [[0.0, 3.0], [6.0, 9.0]]
    assert [w["percent"] for w in credit["per_window"]] == [100.0, 0.0] and credit["percent"] == 50.0
    assert all("credit_raw" not in w for w in block["timeline"])    # the sums stay internal, like `raw`


def test_a_take_with_nothing_compared_has_a_null_credit():
    block = score.timeline_block([{"t_s": (0.0, 5.0), "compared": False}], "reps", RULES)
    assert block["credit"] is None and block["value"] == 0


def test_an_unaligned_take_has_a_null_credit(blind_follower):
    a = run(str(ROOT / "fixtures/input/expected/exercise/animation.json"), blind_follower(), score=score_block).analysis
    assert a["score"]["credit"] is None and a["score"]["value"] == 0
    assert validate_analysis(a) is a and not list(VALIDATOR.iter_errors(a))


def test_the_credit_changes_no_other_field_of_the_score(monkeypatch):
    """The block without its credit is the block the windows give without their credit sums."""
    n, fps = 300, 30
    fault = {"measure": "elbow_flexion", "side": "left", "joint": "left_elbow", "magnitude_deg": 30.0, "threshold_deg": 20.0,
             "runs": [[10, 60]], "expected_frames": [10, 60], "coverage": 1.0, "text": "left elbow bent more",
             "follower_t_s": [0.3, 2.0], "at_s": 0.3}
    off = aligned(n=n, offset=degrees_off({m: 0.4 for m in MEASURES}, RULES))
    with_credit = score.compute_timeline(analysis([fault]), off, np.arange(n) / fps, RULES, expected_times=np.arange(n) / fps)
    original = score.window_score
    monkeypatch.setattr(score, "window_score", lambda *a, **k: {
        key: v for key, v in (original(*a, **k) or {}).items() if key != "credit_raw"} or None)
    without = score.compute_timeline(analysis([fault]), off, np.arange(n) / fps, RULES, expected_times=np.arange(n) / fps)
    assert without["credit"] is None and with_credit["credit"] is not None
    assert {k: v for k, v in with_credit.items() if k != "credit"} == {k: v for k, v in without.items() if k != "credit"}


def test_the_warning_cap_does_not_apply_to_the_credit():
    block = score.compute_timeline(analysis(), aligned(n=300), np.arange(300) / 30, RULES, expected_times=np.arange(300) / 30)
    warned = score.cap_by_warnings(block, {"warnings": [{"code": "low_match", "text": "x"}]}, RULES)
    assert warned["value"] == 59 and warned["credit"] == block["credit"] and warned["credit"]["percent"] == 100.0


# ---------------------------------------------------------------- the documents
@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.name)
def test_every_golden_carries_a_credit_aligned_with_its_compared_timeline(path):
    doc = json.loads(path.read_text())
    s, credit = doc["score"], doc["score"]["credit"]
    assert doc["schema_version"] == "1.13.0" and not list(VALIDATOR.iter_errors(doc)) and validate_analysis(doc) is doc
    assert [w["t_s"] for w in credit["per_window"]] == [w["t_s"] for w in s["timeline"] if w["compared"]]
    assert credit["levels"]["normal"] == {k: credit[k] for k in ("percent", "points", "max_points")}
    assert credit["grade"] == score.credit_grade(credit["percent"])
    assert credit["points"] == pytest.approx(sum(w["points"] for w in credit["per_window"]), abs=len(credit["per_window"]))


def test_the_validator_refuses_a_per_window_that_does_not_follow_the_timeline():
    doc = json.loads(GOLDENS[0].read_text())
    doc["score"]["credit"]["per_window"] = doc["score"]["credit"]["per_window"][1:] or []
    with pytest.raises(OutputError, match="per_window"):
        validate_analysis(doc)


# ---------------------------------------------------------------- the formula, restated from the per-frame z
REF_BANDS = [(0.5, 1.0), (1.0, 0.6), (2.0, 0.2)]
REF_DIFFICULTY = {"easy": (1.5, 0.75), "normal": (1.0, 1.0), "hard": (0.7, 1.5)}


def _example_step(path):
    """Seconds per frame of the example clip, read from its own file: first to last time over its frames less one."""
    times = [f["t"] for f in json.loads(Path(path).read_text())["frames"]]
    return (times[-1] - times[0]) / (len(times) - 1)


def _reference(monkeypatch, expected, follower):
    """The formula restated: capture every compared window's per-frame z through a spy on `score.timeline_window`, then
    credit, points and percent per level, unrounded, with a frame lasting what it does on the example's clock."""
    captured, original = [], score.timeline_window
    step = _example_step(expected["path"])

    def spy(span, analysis, aligned, frames, rules, p, tempo, ratio, timed=True, frame_s=None):
        out = original(span, analysis, aligned, frames, rules, p, tempo, ratio, timed, frame_s)
        frames = np.asarray(frames)
        if out.get("compared", True) and np.size(frames):
            idx = np.asarray(aligned["exp_to_fol"])[frames]
            zs = []
            for name in MEASURES:
                d = np.asarray(aligned["follower"][name])[idx] - np.asarray(aligned["expected"][name])[frames]
                z = np.abs(d) / score.threshold_of(name, rules)
                if np.isfinite(z).mean() >= 0.5:
                    zs.append(z)
            captured.append((span, np.vstack(zs) if zs else np.zeros((0, len(frames)))))
        return out

    monkeypatch.setattr(score, "timeline_window", spy)
    result = golden_run(expected, follower)
    rows = {}
    for diff, (tol, mult) in REF_DIFFICULTY.items():
        pts = poss = 0.0
        for span, z in captured:
            c = np.full(z.shape, 0.0)
            for edge, value in reversed(REF_BANDS):
                c = np.where(z / tol <= edge, value, c)
            c = np.where(np.isfinite(z), c, np.nan)
            pts += np.nansum(c) * step * 100 * mult
            poss += np.isfinite(c).sum() * step * 100 * mult
        rows[diff] = (pts, poss)
    return result.analysis["score"], rows


@pytest.mark.parametrize("name", ["analysis.example.json", "analysis.fault-capped.example.json"])
def test_the_credit_equals_the_formula_restated_from_the_per_frame_z(monkeypatch, name):
    """A take compared as a whole (5 s windows) and one compared rep by rep. Not the owner's script: the formula, restated."""
    golden = json.loads((ROOT / "fixtures/output" / name).read_text())
    s, rows = _reference(monkeypatch, {"path": str(ROOT / golden["expected"]["path"])},
                         {"path": str(ROOT / golden["follower"]["path"]), "take_id": golden["follower"]["take_id"]})
    assert s["credit"] == golden["score"]["credit"]
    for level, (pts, poss) in rows.items():
        shown = s["credit"]["levels"][level]
        assert shown["points"] == int(score.round_half_up(pts)) and shown["max_points"] == int(score.round_half_up(poss))
        assert shown["percent"] == pytest.approx(100 * pts / poss, abs=0.05)


# What the owner's replay script printed for the four goldens on the follower's clock (normal / easy / hard: percent, points,
# max points), kept as provenance (the team's branch, 7181813). Points differ now (they are counted on the example's clock); the
# percents differ only where a window's weight changed from its follower seconds to its example frames.
FOLLOWER_CLOCK_SCRIPT_OUTPUT = {
    "analysis.example.json": {"easy": (92.2, 3651, 3960), "normal": (87.5, 4622, 5280), "hard": (81.2, 6433, 7920)},
    "analysis.no-faults.example.json": {"easy": (99.5, 4214, 4235), "normal": (97.8, 5525, 5647), "hard": (94.1, 7967, 8470)},
    "analysis.fault-capped.example.json": {"easy": (97.7, 4944, 5060), "normal": (93.3, 6294, 6747),
                                           "hard": (86.6, 8763, 10120)},
    "analysis.double-capped.example.json": {"easy": (79.6, 7262, 9120), "normal": (66.1, 8036, 12160),
                                            "hard": (52.0, 9484, 18240)},
}


@pytest.mark.parametrize("name", FOLLOWER_CLOCK_SCRIPT_OUTPUT)
def test_the_golden_percents_stay_within_half_a_point_of_what_the_follower_clock_script_printed(name):
    path = ROOT / "fixtures/output" / name
    if not path.exists():
        pytest.skip("written only while the rules ship a ceiling")
    levels = json.loads(path.read_text())["score"]["credit"]["levels"]
    for level, (percent, _, _) in FOLLOWER_CLOCK_SCRIPT_OUTPUT[name].items():
        assert levels[level]["percent"] == pytest.approx(percent, abs=0.5), (name, level)


def test_credit_grades_run_f_to_s_on_their_own_scale():
    g = score.credit_grade
    assert [g(p) for p in (100, 95, 94.9, 85, 75, 65, 55, 45, 44.9, 30, 0)] == ["S", "S", "A", "A", "B", "C", "D", "E", "F", "F", "F"]
    assert score.CREDIT_GRADES[-1] == [30, "F"], "F's mark sits at 30; under it is still F"
    assert score.BANDS[0] == [90, "A"], "the score's own bands stay A to F"
