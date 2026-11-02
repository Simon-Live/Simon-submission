"""TICKET-094 (docs/specs/measure-branch-cuts.md): the measures read with `arctan2` do not jump by 360 degrees where their
branch cut falls, a follower and a reference cannot differ by a whole turn, and a clip with no wrap reads as it did."""
from pathlib import Path

import numpy as np
import pytest

from part5.io import load_clip
from part5.measures import WINDOW_LOW, _continuous, _forward_from_down, _sagittal, compute
from test_measures import hinged_trunk, m, pose

ROOT = Path(__file__).resolve().parent.parent
LEAN = (0.0, 30.0, 90.0)       # the trunk upright, leaning, and hinged level (a deep hinge with the arms hanging)
SIDES = ("left", "right")


def arm_pose(flexion, lean=0.0, side="left", length=0.3):
    """The standing pose with the trunk `lean` degrees forward and the `side` upper arm raised `flexion` degrees forward
    from the trunk's down direction, in the sagittal plane. 0 hangs along the trunk, 90 is square to it, 180 points along
    it toward the head (overhead when upright), more than 180 is past that."""
    t, a = np.radians(lean), np.radians(flexion - lean)    # the arm's own angle from straight down
    top = 0.5 * np.array([0.0, np.cos(t), np.sin(t)])
    sh = {"left": top + [0.2, 0, 0], "right": top - [0.2, 0, 0]}
    elbow = sh[side] + length * np.array([0.0, -np.cos(a), np.sin(a)])
    return pose(left_shoulder=list(sh["left"]), right_shoulder=list(sh["right"]), **{f"{side}_elbow": list(elbow)})


def clip(poses):
    return np.concatenate(poses)


def old_arm(positions):
    """The upper_arm_forward of before TICKET-094, for the side-by-side checks: the raw sum, the cut at straight up."""
    out = {}
    for side in SIDES:
        sh, el = positions[:, 5 + (side == "right")], positions[:, 7 + (side == "right")]
        spine = 0.5 * (positions[:, 5] + positions[:, 6]) - 0.5 * (positions[:, 11] + positions[:, 12])
        out[side] = _forward_from_down(el - sh) + _sagittal(spine)
    return out


# --- AC-BC-01: an arm raised from down, through overhead, and back down reads its flexion without a jump ---
@pytest.mark.parametrize("lean", LEAN)
@pytest.mark.parametrize("side", SIDES)
def test_ac_bc_01_an_arm_raised_through_overhead_and_back_reads_its_flexion_without_a_jump(lean, side):
    flexion = np.concatenate([np.arange(0, 211), np.arange(210, -1, -1)]).astype(float)
    positions = clip([arm_pose(f, lean, side) for f in flexion])
    got = compute(positions)[f"{side}_upper_arm_forward"]
    assert np.allclose(got, flexion, atol=1e-6)
    assert np.max(np.abs(np.diff(got))) <= 1.0 + 1e-6


def test_ac_bc_01_the_check_would_fail_on_the_old_formula():
    """The negative control: the same raise, read as before, jumps by a whole turn where the arm crosses straight up."""
    flexion = np.arange(0, 211).astype(float)
    old = old_arm(clip([arm_pose(f, 0.0, "left") for f in flexion]))["left"]
    assert np.max(np.abs(np.diff(old))) > 300


# --- AC-BC-02: the two sides of the old cut read two degrees apart ---
@pytest.mark.parametrize("lean", LEAN)
def test_ac_bc_02_an_arm_one_degree_either_side_of_the_old_cut_reads_two_degrees_apart(lean):
    below, above = (m(arm_pose(180 + d, lean))["left_upper_arm_forward"] for d in (-1.0, 1.0))
    assert above - below == pytest.approx(2.0, abs=1e-6)


# --- AC-BC-03: no whole-clip offset between a follower and a reference ---
def test_ac_bc_03_a_follower_and_a_reference_that_start_on_opposite_sides_of_the_cut_do_not_differ_by_a_turn():
    """Both hold the arm overhead and drift across the old cut, in opposite directions: the reference starts below it
    and ends above, the follower starts above it and ends below. A series unwrapped from its first frame alone would put
    one of them a turn from the other for the whole clip."""
    n = 60
    reference = 176 + 8 * np.arange(n) / (n - 1)       # 176 to 184
    follower = 184 - 8 * np.arange(n) / (n - 1)        # 184 to 176
    key = "left_upper_arm_forward"
    ref = compute(clip([arm_pose(f) for f in reference]))[key]
    fol = compute(clip([arm_pose(f) for f in follower]))[key]
    assert np.allclose(ref, reference, atol=1e-6) and np.allclose(fol, follower, atol=1e-6)
    assert np.max(np.abs(ref - fol)) <= 8.0 + 1e-6


def test_ac_bc_03_the_clip_is_put_on_the_branch_of_its_median():
    """The rule that decides the branch: a clip whose median lies outside the window is moved by whole turns until it is
    inside, and the same shape of clip a turn apart comes back identical."""
    low = WINDOW_LOW["upper_arm_forward"]
    base = np.array([10.0, 40.0, 100.0, 170.0, 120.0, 20.0])
    for turn in (-2, -1, 0, 1):
        got = _continuous(base + 360 * turn, "upper_arm_forward")
        assert np.array_equal(got, base)
        assert low <= np.median(got) < low + 360


def test_ac_bc_03_a_wrap_inside_a_clip_is_closed_whichever_way_the_arm_crosses():
    over_the_front = np.array([160.0, 170.0, 179.0, -179.0, -170.0])     # raised past the cut, then on
    over_the_back = np.array([-170.0, -179.0, 179.0, 170.0, 160.0])      # lowered through it
    assert np.allclose(_continuous(over_the_front, "upper_arm_forward"), [160, 170, 179, 181, 190])
    assert np.allclose(_continuous(over_the_back, "upper_arm_forward"), [190, 181, 179, 170, 160])


# --- AC-BC-04: a clip with no wrap, and a median inside the window, is as it was, bit for bit ---
def test_ac_bc_04_values_without_a_wrap_keep_their_exact_bits_and_nan_stays_nan():
    rng = np.random.default_rng(5)
    series = 60 + 140 * np.sin(np.linspace(0, 12, 400)) + rng.uniform(-3, 3, 400)     # -83 to 203, small steps
    series[::17] = np.nan
    series[3] = -0.0
    got = _continuous(series, "upper_arm_forward")
    assert got.tobytes() == series.tobytes()


def _old_measures(positions):
    """The four measures as they were: the raw `arctan2` angles, the sums as they were written."""
    p = np.asarray(positions, float)
    spine = 0.5 * (p[:, 5] + p[:, 6]) - 0.5 * (p[:, 11] + p[:, 12])
    trunk = _sagittal(spine)
    out = {"trunk_lean_forward": trunk,
           "head_forward": _sagittal(p[:, 0] - 0.5 * (p[:, 5] + p[:, 6])) - trunk}
    for side, (sh, el, hp, kn) in {"left": (5, 7, 11, 13), "right": (6, 8, 12, 14)}.items():
        out[f"{side}_upper_arm_forward"] = _forward_from_down(p[:, el] - p[:, sh]) + trunk
        out[f"{side}_thigh_forward"] = _forward_from_down(p[:, kn] - p[:, hp])
    return out


def committed_clips():
    """Seed 5's followers, the expected clips and the held-out takes the check reads: no arm passes overhead in them."""
    paths = sorted((ROOT / "fixtures/input/followers").glob("*/*/skeleton.json"))[::40]
    paths += sorted((ROOT / "fixtures/input/expected").glob("*/animation.json"))
    paths += sorted((ROOT / "fixtures/input/heldout").glob("*/*/skeleton.json"))[::40]
    return paths


def test_ac_bc_04_the_committed_takes_read_exactly_as_before():
    paths = committed_clips()
    assert len(paths) >= 8
    for path in paths:
        positions = load_clip(path).positions
        new = compute(positions)
        for name, old in _old_measures(positions).items():
            assert np.array_equal(new[name], old, equal_nan=True), f"{path.relative_to(ROOT)}: {name}"


# --- AC-BC-05: the one real clip with an arm past vertical ---
def test_ac_bc_05_the_real_stretch_clip_has_no_jump_of_a_turn_in_any_of_the_four_measures():
    positions = load_clip(ROOT / "fixtures/input/mismatch/part2-stretch/skeleton.json").positions
    new, old = compute(positions), _old_measures(positions)
    for name in old:
        assert np.nanmax(np.abs(np.diff(new[name]))) < 100, name
    jumped = [n for n, v in old.items() if np.nanmax(np.abs(np.diff(v))) > 300]
    assert jumped, "the clip no longer shows the wrap this test records"
    assert set(jumped) <= {"left_upper_arm_forward", "right_upper_arm_forward", "head_forward"}


# --- AC-BC-06: the other measures that read an arctan2 (docs/specs/measure-branch-cuts.md "Audit") ---
def test_ac_bc_06_the_thigh_raised_from_behind_past_vertical_is_continuous():
    angles = np.arange(-80, 201).astype(float)
    positions = clip([pose(left_knee=list(0.4 * np.array([0.0, -np.cos(np.radians(a)), np.sin(np.radians(a))]) + [0.1, 0, 0]))
                      for a in angles])
    got = compute(positions)["left_thigh_forward"]
    assert np.allclose(got, angles, atol=1e-6)
    assert np.max(np.abs(np.diff(_old_measures(positions)["left_thigh_forward"]))) > 300   # the control


def test_ac_bc_06_the_trunk_hinged_from_upright_to_folded_flat_and_past_is_continuous():
    hinges = np.arange(-60, 201).astype(float)
    positions = clip([hinged_trunk(h) for h in hinges])
    got = compute(positions)["trunk_lean_forward"]
    assert np.allclose(got, hinges, atol=1e-6)
    assert np.max(np.abs(np.diff(_old_measures(positions)["trunk_lean_forward"]))) > 300


def test_ac_bc_06_the_head_against_a_folded_trunk_is_the_signed_difference_not_a_turn_off():
    """The trunk folded 170 degrees, the head swung from 90 back to 120 forward of it: the head's own angle passes
    straight down (180) on the way, where the angle of the head alone wraps."""
    lean, length = 170.0, 0.5
    top = length * np.array([0.0, np.cos(np.radians(lean)), np.sin(np.radians(lean))])
    relative = np.arange(-90, 121).astype(float)

    def head(r):
        a = np.radians(lean + r)
        nose = top + 0.25 * np.array([0.0, np.cos(a), np.sin(a)])
        return pose(left_shoulder=list(top + [0.2, 0, 0]), right_shoulder=list(top - [0.2, 0, 0]), nose=list(nose))

    positions = clip([head(r) for r in relative])
    got = compute(positions)["head_forward"]
    assert np.allclose(got, relative, atol=1e-6)
    assert np.max(np.abs(np.diff(_old_measures(positions)["head_forward"]))) > 300


def test_ac_bc_06_every_other_angle_measure_is_bounded_by_its_formula():
    """shoulder_tilt, trunk_lean_side, the out angles and the knee valgus end in an arcsin, or in an arctan2 against a
    length that cannot be negative, so none can wrap: random bodies, every pose, stay in -90..90."""
    rng = np.random.default_rng(94)
    got = compute(rng.normal(size=(3000, 17, 3)))
    bounded = [n for n in got if n.endswith(("_out", "_valgus")) or n in ("shoulder_tilt", "trunk_lean_side")]
    assert len(bounded) == 2 * 4 + 2 + 2          # the four sided out measures, valgus on both sides, two centre ones
    for name in bounded:
        assert np.all(np.abs(got[name]) <= 90.0 + 1e-9), name
    for name in ("left_elbow_flexion", "right_knee_flexion"):
        assert np.all((got[name] >= 0) & (got[name] <= 180))


# --- AC-BC-07: gaps and edges ---
def test_ac_bc_07_a_wrap_is_closed_across_frames_without_a_value():
    flexion = np.arange(150, 211).astype(float)
    positions = clip([arm_pose(f) for f in flexion])
    positions[20:30, 7] = np.nan                       # the left elbow is lost for ten frames, across the old cut
    got = compute(positions)["left_upper_arm_forward"]
    assert np.all(np.isnan(got[20:30]))
    valid = np.r_[0:20, 30:len(flexion)]
    assert np.allclose(got[valid], flexion[valid], atol=1e-6)


def test_ac_bc_07_a_clip_with_nothing_to_read_or_one_frame_is_returned_as_it_is():
    assert _continuous(np.full(5, np.nan), "head_forward").shape == (5,)
    assert np.all(np.isnan(_continuous(np.full(5, np.nan), "head_forward")))
    assert _continuous(np.array([]), "head_forward").shape == (0,)
    assert _continuous(np.array([200.0]), "upper_arm_forward")[0] == 200.0      # inside [-120, 240)
    assert _continuous(np.array([-170.0]), "upper_arm_forward")[0] == 190.0     # outside: the branch of the window


# --- Limits (docs/specs/measure-branch-cuts.md): a real movement across a run of lost frames can read as a wrap ---
def test_limit_a_real_movement_over_half_a_turn_across_lost_frames_reads_as_a_wrap():
    """R5 of the 1.14.1 review, pinned as the limit it is, not as a wanted behaviour: the steps are judged between the
    frames that have a value, so an arm that really moved from -70 to 170 degrees (240 degrees) over 20 lost frames is
    indistinguishable from one that crossed the cut and moved 120 degrees the other way. `_continuous` closes it as a
    wrap: the clip reads 120 degrees apart (290 then 170 for `upper_arm_forward`), not 240. Today's output is pinned, so
    a change to this limit is seen and decided, not made by accident. No committed clip loses frames across a step."""
    seen = np.r_[np.full(10, -70.0), np.full(20, np.nan), np.full(10, 170.0)]
    arm = _continuous(seen, "upper_arm_forward")
    assert np.all(arm[:10] == 290.0) and np.all(np.isnan(arm[10:30])) and np.all(arm[30:] == 170.0)
    assert arm[30] - arm[9] == -120.0          # the movement it reads; the one the arm made was +240
    head = _continuous(seen, "head_forward")
    assert np.all(head[:10] == -70.0) and np.all(head[30:] == -190.0)
    short = np.r_[np.full(10, -70.0), np.full(3, np.nan), np.full(10, 170.0)]   # a gap of any length, three frames too
    assert _continuous(short, "upper_arm_forward")[-1] - _continuous(short, "upper_arm_forward")[0] == -120.0
