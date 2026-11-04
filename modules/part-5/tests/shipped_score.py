"""Which score the rules ship, for the tests whose expectation depends on it (ADR-0018, ADR-0019, TICKET-047, TICKET-060), and
the one home of the helpers, the fixtures' bodies and the frozen hashes the score tests share.

`simon.score.v3` ships: it held all five targets on score seed 61 (docs/thresholds-score-v3.md). `make score-fallback` still
puts v1 back with `make test` green (proven for v2 on seed 59 and for v3 before the freeze). A test that pins a value, a golden or a ceiling reads
here: `capped_only` skips it when the rules ship v1 (no ceiling), `v3_only` and `v1_only` skip it for the other versions, and
`by_version` gives the number that version has. A test of the v2 or v3 code itself (the weight, the ceilings, the floor rule)
builds its own rules from `v2_rules` or `v3_rules` and does not need either, whichever score ships.

The synthetic takes (`aligned`, `fault`, `analysis`, `window`, `timed_take`), the add-up checks, `small_set` and `seed5_run`
are used by tests/test_score_v2.py and tests/test_score_v3.py and live here once; the fixtures that hand them out are in
tests/conftest.py (`seed5_scored`, `report_as`). `UNMEASURED_TEMPO` and `tempo_items` are the tempo checks of
tests/test_profiles.py, tests/test_profiles_tempo.py, tests/test_score_timeline.py and tests/test_reps.py."""
import copy
import functools
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import score, score_report
from part5.detect import load_rules
from part5.measures import MEASURES
from part5.score_report import v1_of, v2_of

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "part5" / "rules.json"
V1, V2, V3 = score.VERSION_V1, score.VERSION_V2, score.VERSION_V3
SHIPPED = json.loads(RULES.read_text())["score"]["version"]
IS_V3 = score.ships(V3)
IS_CAPPED = score.has_ceiling()   # v2 or v3: a take that reports a fault has a ceiling and `fault_cap`
# The floor ADR-0018's rule picked on seed 5 (docs/thresholds.md), and picked again, unchanged, under the v3 code (ADR-0019):
# the one literal the tests build v2 and v3 with. While the rules ship v3 a test checks that this is their `range_floor`;
# a re-run of the rule that moved it changes it here only.
FLOOR = 0.75
# The hashes the freezes and the record name, written once. `params_sha256` of the frozen blocks kept in the rules, and the hash
# of the detection rules (the `score` key left out): attempt 5 (max_jitter_deg 4 on the two foot measures, ADR-0015 Amendment 4);
# 0a559e18 at attempt 4 (the floor split by measure class and the persistence constants in the rules, N2 and residual 5),
# c53a751e before its recheck, e340940f at fb1d6e8 for attempt 3, b76e6ca3 at fbb0bea.
V1_SHA = "e818635bb46b7062f57e335f2940edd35d01835edaaaffed9339fdbfb79eaa62"   # score.v1, recorded for seeds 47 and 53
V2_SHA = "60116de4cede436c574b91b15a74a7f0c5561790ac6f61cf9181a8317575fe95"   # score.v2, frozen for seed 59 (ADR-0018)
DETECTION_SHA = "c92ae9a8524c559741cdaebcd14bb5305e91479d19123e15c3a5e14efb1337fb"

capped_only = pytest.mark.skipif(not IS_CAPPED, reason="the rules ship simon.score.v1 (make score-fallback): a ceiling expectation")
v3_only = pytest.mark.skipif(not IS_V3, reason="the rules do not ship simon.score.v3: a v3 expectation")
v1_only = pytest.mark.skipif(IS_CAPPED, reason="the rules ship a score with a ceiling (v2 or v3): a v1 expectation")
# A test written for v1 (a teammate's, kept byte for byte) that a ceiling or a weighted miss breaks. It runs again whenever the
# rules ship v1 (`make score-fallback`); the property it pins is pinned for the value before the cap in tests/test_score_v3.py.
not_v3 = pytest.mark.skipif(IS_V3, reason="the rules ship simon.score.v3: its ceiling of 79 lowers the take below the mean of its windows (ADR-0019)")


def by_version(v1, v2, v3=None):
    """The number the shipped score has: `v1`, `v2` or `v3` by the version the rules ship (`v3` is left out by a test that a
    `not_v3` mark skips under v3: that arm could never be read)."""
    return {V1: v1, V2: v2, V3: v3}[SHIPPED]


def frozen_v1():
    """The frozen v1 params of the rules in the tree: the `v1` block of a v2 or v3 score section, else the section itself."""
    return v1_of(load_rules())


def v2_block(floor=FLOOR):
    """The v2 score section built from the frozen v1 params and `floor`: v2 as designed, whichever score the rules ship."""
    return score.block_v2(frozen_v1(), floor)


def frozen_v2():
    """The frozen v2 params (`V2_SHA`): kept verbatim in a v3 score section. A v1 tree (after `make score-fallback`) does
    not keep them, so they are rebuilt from the frozen v1 params and FLOOR: the same dict, which a test pins by its hash."""
    try:
        return v2_of(load_rules())
    except ValueError:
        return v2_block()


def v2_rules(floor=FLOOR):
    """The tree's rules with the v2 score section (`v2_block(floor)`)."""
    return {**load_rules(), "score": v2_block(floor)}


def v3_block(floor=FLOOR):
    """The v3 score section built from the frozen v1 and v2 params and `floor`: v3 as designed, whichever score the rules ship."""
    return score.block_v3(frozen_v1(), frozen_v2(), floor)


def v3_rules(floor=FLOOR):
    """The tree's rules with the v3 score section (`v3_block(floor)`)."""
    return {**load_rules(), "score": v3_block(floor)}


# ---------------------------------------------------------------- synthetic takes, shared by test_score_v2 and test_score_v3
N = 20
# small v1 params of the tests (not the shipped ones): a light fault costs a couple of points, the arithmetic is easy to read
TEST_V1 = {"version": "simon.score.v1", "z0": 0.0, "z1": 1.0, "s_max": 4.0, "base": 10, "slope": 5.0, "cap": 30.0,
           "bands": [[90, "A"], [80, "B"], [70, "C"], [60, "D"], [0, "F"]], "calibrated_on": "test"}


def fresh_v1():
    """A copy of `TEST_V1` a test may change."""
    return copy.deepcopy(TEST_V1)


def aligned(still=True, n=N, nan=False, offset=None):
    """Every measure is zero in the follower (NaN with `nan`: nothing to measure); in the expected clip every measure is
    still (range 0) or swings 100 degrees. `offset` maps a measure to how many degrees the follower sits off the example
    in it, a number or one per frame; the measures it does not name stay 0."""
    swing = np.linspace(0.0, 100.0, n)
    exp = {m: (np.zeros(n) if still else swing.copy()) for m in MEASURES}
    off = offset or {}
    fol = {m: np.full(n, np.nan) if nan else np.zeros(n) + np.asarray(off.get(m, 0.0)) for m in MEASURES}
    return {"expected": exp, "follower": fol, "exp_to_fol": list(range(n))}


def degrees_off(offset, rules):
    """`offset` (measure -> how many of its thresholds the follower sits off the example, a number or one per frame) as the
    degrees `aligned(offset=)` takes, each measure's threshold read from `rules`."""
    return {name: np.asarray(v) * score.threshold_of(name, rules) for name, v in (offset or {}).items()}


def fault(measure="foot_out", side="left", mag=20.0, thr=10.0, runs=((0, 9),), cov=1.0):
    return {"measure": measure, "side": side, "magnitude_deg": mag, "threshold_deg": thr, "text": "left foot too far out",
            "runs": [list(r) for r in runs], "coverage": cov, "expected_frames": list(runs[0])}


def analysis(faults=(), **extra):
    return {"status": {"code": "ok"}, "faults": list(faults), **extra}


def window(raw, k):
    return {"t_s": (5.0 * k, 5.0 * k + 5.0), "raw": raw, "value": int(round(raw)), "grade": score.grade(int(round(raw))),
            "components": {"faults": 100 - raw, "similarity": 0.0}, "misses": []}


def timed_take(rules, seconds, misses, fps=30):
    """A take of `seconds` with `misses` one-second faults spread evenly, scored in 5 s windows under `rules`. The expected
    clip is still, so every miss is weighted by the floor and costs a fractional number of points."""
    n = seconds * fps
    starts = np.linspace(0, n - fps, misses, dtype=int) if misses else []
    faults = [{**fault(runs=((int(s), int(s) + fps - 1),)), "follower_t_s": [s / fps, s / fps + 1], "at_s": s / fps} for s in starts]
    return score.compute_timeline(analysis(faults), aligned(n=n), np.arange(n) / fps, rules)


def lengths(rules):
    """`(one miss in a minute, ten in ten minutes, ten in a minute)` scored under `rules` (ADR-0013's length-agnostic score)."""
    return timed_take(rules, 60, 1), timed_take(rules, 600, 10), timed_take(rules, 60, 10)


def check_share_of_the_take(one, ten, crowded):
    """ADR-0013 before any cap: a miss a minute costs what ten in ten minutes cost, and more misses in the same time cost more."""
    before = score_report.uncapped_value
    assert before(one) == pytest.approx(before(ten), abs=1) and before(one) > before(crowded)


def check_windows_add_up(block, compared):
    """The `compared` windows of a score block each add up to their value (the points shown are rounded to 0.1, the value to 1:
    within 0.6) and the take is the mean of their values before any cap, within a point."""
    windows = [w for w in block["timeline"] if w["compared"]]
    assert len(windows) == compared
    for w in windows:
        assert w["value"] == pytest.approx(100 - sum(m["points"] for m in w["misses"]) - w["components"]["similarity"], abs=0.6)
        for m in w["misses"]:
            assert m["text"] and m["points"] > 0
            if block["basis"] == "windows":
                assert w["t_s"][0] - 1 <= m["at_s"] <= w["t_s"][1]
    assert score_report.uncapped_value(block) == pytest.approx(sum(w["value"] for w in windows) / len(windows), abs=1)


# ---------------------------------------------------------------- tempo, shared by the profile, timeline and rep tests
UNMEASURED_TEMPO = {"ratio": None, "cue": None}   # a tempo nothing was measured for: a low match (ADR-0014 Amendment 4) or under 1 s


def tempo_items(a):
    """The tempo items of a document's `insights` (`kind` "tempo"); `a` is the document, or any dict with an `insights` list."""
    return [i for i in a["insights"] if i["kind"] == "tempo"]


# ---------------------------------------------------------------- seed 5 and the small sets, shared by the two files
def small_set(tmp_path, keep):
    """A labels.json under `tmp_path` with the seed 5 takes named in `keep`, their paths made absolute."""
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    labels["takes"] = [t for t in labels["takes"] if t["take_id"] in keep]
    for t in labels["takes"]:
        for key in ("expected", "follower", "expected_feet", "follower_feet"):
            if t.get(key):
                t[key] = str(ROOT / t[key])
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    return tmp_path


@functools.lru_cache(maxsize=None)
def seed5_run():
    """Seed 5 through the pipeline once per process: `(labels, the shipped rules, [(take, PipelineResult)])`. The results are
    only read (never changed) by the tests that take them from `seed5_scored`."""
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    rules = load_rules()
    return labels, rules, score_report.run_set(labels, rules)


@functools.lru_cache(maxsize=None)
def lateral_raise_run():
    """The real fast lateral-raise follower (8 reps, compared rep by rep; tests/test_reps.py) through the pipeline once per
    process. It reports two faults and its mean of windows is 82 before any ceiling."""
    from part5.pipeline import run
    lateral = ROOT / "fixtures/input/real/lateral-raise"
    return run(str(lateral / "pexels-5319084/animation.json"), str(lateral / "pexels-40297504/animation.json"))
