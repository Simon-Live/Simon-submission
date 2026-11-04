"""Properties of Part 5's score (docs/specs/scoring-validity.md AC-SV08, TICKET-082): eight named claims that must hold for
any input, checked by `hypothesis` on committed seed 5 takes through Part 5's own pipeline.

Derandomized (`derandomize=True`, no example database, no deadline) and small (`MAX_EXAMPLES` per property), so the file is
the same every run and takes well under a minute. A property the code does not hold is never loosened: it is
`xfail(strict=True)` with `TICKET-083: <what>` (strict, so the day it passes the run says so) and its numbers are in
docs/evaluation.md. ADR-0019: the score is frozen; ASM-001: the input is in the subject's frame, hip midpoint at the origin.

| Id | Property |
| P1 | `score.value` is an integer in 0..100 and `score.grade` is its band, whatever is planted or added |
| P2 | an example compared with itself scores 100, grade A, and reports no fault |
| P3 | a translation within 1 cm changes nothing; a larger one is a typed `InputError` |
| P4 | a yaw of the follower about the vertical changes nothing (xfail: TICKET-083) |
| P5 | a uniform scale of the follower changes nothing |
| P6 | mirroring both clips swaps the sides of the faults and changes nothing else |
| P7 | a NaN or infinite coordinate is a typed `InputError` naming the frame and the joint |
| P8 | frames with every joint null are hidden measures: nothing is invented, and a mostly empty take is `no_usable_measures` |
"""
import copy
import functools
import json
import math
import random
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_score_validity as sv  # noqa: E402
from part5 import score  # noqa: E402
from part5.io import JOINTS, InputError  # noqa: E402

MAX_EXAMPLES = 6
PROPERTY = settings(derandomize=True, deadline=None, max_examples=MAX_EXAMPLES, database=None)
EXPECTED = {"exercise": ROOT / "fixtures/input/expected/exercise/animation.json",
            "dance": ROOT / "fixtures/input/expected/dance/animation.json"}
CORRECT = ["exercise_front_good_00_correct", "exercise_45_good_01_correct", "exercise_side_good_00_correct",
           "dance_front_good_00_correct"]
FAULTED = ["exercise_front_good_02_arms_wider-right", "exercise_front_good_03_foot_out-right",
           "exercise_front_good_05_elbow_bent-left", "exercise_45_good_06_trunk_lean-center",
           "exercise_side_good_07_knee_caving-right", "dance_front_good_05_elbow_bent-left"]
TAKES = CORRECT + FAULTED
ODD = set(sv.ODD_MEASURES)


@functools.lru_cache(maxsize=None)
def take_of(take_id):
    return next(t for t in sv.pool() if t["take_id"] == take_id)


@functools.lru_cache(maxsize=None)
def expected_of(set_name):
    return sv.load_doc(EXPECTED[set_name])


def follower_of(take_id):
    """A fresh copy of the take's follower clip (a transform never edits it, but a test may)."""
    return sv.load_doc(ROOT / take_of(take_id)["follower"])


@functools.lru_cache(maxsize=None)
def baseline(take_id):
    """The untransformed outcome of a take against its own example."""
    return sv.outcome(sv.analyse(expected_of(take_of(take_id)["set"]), follower_of(take_id), take_id))


def run(take_id, follower):
    return sv.outcome(sv.analyse(expected_of(take_of(take_id)["set"]), follower, take_id))


def same_verdict(a, b):
    """Equal score, grade and fault list (measure, side, direction and size)."""
    return a["value"] == b["value"] and a["grade"] == b["grade"] and sorted(a["faults"]) == sorted(b["faults"])


# ---------------------------------------------------------------- P1
@PROPERTY
@given(take=st.sampled_from(TAKES), joint=st.sampled_from(sorted(sv.PLANTED)), deg=st.floats(0.0, 60.0),
       sigma=st.floats(0.0, 0.03), seed=st.integers(0, 2 ** 16), other_movement=st.booleans())
def test_p1_score_is_an_integer_in_0_to_100_and_the_grade_is_its_band(take, joint, deg, sigma, seed, other_movement):
    follower = sv.noisy_doc(sv.plant(follower_of(take), joint, deg), sigma, seed)
    set_name = take.split("_")[0]
    example = expected_of("dance" if other_movement and set_name == "exercise" else "exercise" if other_movement else set_name)
    analysis = sv.analyse(example, follower, take)
    out = sv.outcome(analysis)
    assert isinstance(out["value"], int) and 0 <= out["value"] <= 100, out["value"]
    assert out["grade"] == score.grade(out["value"])
    assert 0 <= analysis["score"]["components"]["similarity"] <= score.S_MAX
    if out["warnings"]:
        assert out["value"] <= score.WARNING_CAP, "a take with a warning is capped (ADR-0012)"


# ---------------------------------------------------------------- P2
@PROPERTY
@given(name=st.sampled_from(["exercise", "dance", "part3-squat"]), through_json=st.booleans())
def test_p2_an_example_compared_with_itself_scores_100_and_reports_no_fault(name, through_json):
    doc = sv.load_doc(ROOT / f"fixtures/input/expected/{name}/animation.json")
    twin = json.loads(json.dumps(doc)) if through_json else copy.deepcopy(doc)
    out = sv.outcome(sv.analyse(doc, twin, "twin"))
    assert (out["value"], out["grade"], out["faults"], out["warnings"]) == (100, "A", [], [])


# ---------------------------------------------------------------- P3
@PROPERTY
@given(take=st.sampled_from(TAKES), shift=st.tuples(*[st.floats(-0.009, 0.009)] * 3))
def test_p3_a_translation_within_a_centimetre_changes_nothing(take, shift):
    assert same_verdict(run(take, sv.translate_doc(follower_of(take), shift)), baseline(take))


@PROPERTY
@given(take=st.sampled_from(TAKES), axis=st.integers(0, 2), distance=st.floats(0.02, 5.0), sign=st.sampled_from([-1.0, 1.0]))
def test_p3_a_translation_beyond_a_centimetre_is_a_typed_input_error(take, axis, distance, sign):
    shift = [0.0, 0.0, 0.0]
    shift[axis] = sign * distance
    with pytest.raises(InputError, match="hip midpoint must be at the origin"):
        run(take, sv.translate_doc(follower_of(take), shift))


# ---------------------------------------------------------------- P4
@pytest.mark.xfail(strict=True, reason="TICKET-083: a yaw of the follower about the vertical changes the score and the fault "
                   "set; the measures read the subject frame's x and z axes (part5/measures.py) and nothing turns the clip back")
@settings(PROPERTY, max_examples=12)
@given(take=st.sampled_from(TAKES), degrees=st.floats(-45.0, 45.0).filter(lambda d: abs(d) >= 1.0))
def test_p4_a_yaw_of_the_follower_changes_nothing(take, degrees):
    got = run(take, sv.yaw_doc(follower_of(take), degrees))
    assert same_verdict(got, baseline(take)), (take, degrees, baseline(take)["value"], got["value"])


# ---------------------------------------------------------------- P5
@PROPERTY
@given(take=st.sampled_from(TAKES), factor=st.floats(0.5, 2.0))
def test_p5_a_uniform_scale_of_the_follower_changes_nothing(take, factor):
    assert same_verdict(run(take, sv.scale_doc(follower_of(take), factor)), baseline(take))


# ---------------------------------------------------------------- P6
def mirrored_faults(faults):
    """`faults` of the mirror image: sides swapped, lateral measures turned (their size changes sign, so compare it by size)."""
    flip = {"more": "less", "less": "more"}
    return sorted((m, sv.SIDES[s], flip[d] if m in ODD else d, abs(g)) for m, s, d, g in faults)


@PROPERTY
@given(take=st.sampled_from(TAKES))
def test_p6_mirroring_both_clips_swaps_the_sides_of_the_faults_and_changes_nothing_else(take):
    example = expected_of(take_of(take)["set"])
    got = sv.outcome(sv.analyse(sv.mirror_doc(example), sv.mirror_doc(follower_of(take)), take))
    base = baseline(take)
    assert (got["value"], got["grade"], got["warnings"]) == (base["value"], base["grade"], base["warnings"])
    assert sorted((m, s, d, abs(g)) for m, s, d, g in got["faults"]) == mirrored_faults(base["faults"])


# ---------------------------------------------------------------- P7
BAD = st.sampled_from([math.nan, math.inf, -math.inf])
SPOTS = st.dictionaries(st.tuples(st.integers(0, 60), st.sampled_from(JOINTS)), st.tuples(st.integers(0, 2), BAD),
                        min_size=1, max_size=3)


@PROPERTY
@given(take=st.sampled_from(CORRECT), spots=SPOTS, in_the_example=st.booleans())
def test_p7_a_nan_or_infinite_coordinate_is_a_typed_error_naming_the_frame_and_the_joint(take, spots, in_the_example):
    set_name = take_of(take)["set"]
    doc = expected_of(set_name) if in_the_example else follower_of(take)
    doc = json.loads(json.dumps(doc))   # a copy; the bad values go in below and come back through JSON's NaN and Infinity
    for (frame, joint), (axis, bad) in spots.items():
        doc["frames"][frame]["joints"][joint][axis] = bad
    doc = json.loads(json.dumps(doc))
    first = min(spots, key=lambda spot: (spot[0], JOINTS.index(spot[1])))   # the loader reads frames, then joints, in order
    example, follower = (doc, follower_of(take)) if in_the_example else (expected_of(set_name), doc)
    with pytest.raises(InputError, match=rf"frames\[{first[0]}\]\.joints\.{first[1]} must be \[x, y, z\] finite numbers"):
        sv.analyse(example, follower, take)


# ---------------------------------------------------------------- P8
def empty_indexes(n, fraction, seed, block):
    """The frames to leave empty: `fraction` of `n`, scattered, or as one block that starts at a seeded place."""
    k = int(fraction * n)
    if block:
        start = random.Random(seed).randint(0, n - k)
        return list(range(start, start + k))
    return random.Random(seed).sample(range(n), k)


@PROPERTY
@given(take=st.sampled_from(CORRECT), fraction=st.floats(0.0, 0.4), seed=st.integers(0, 2 ** 16), block=st.booleans())
def test_p8_a_few_empty_frames_are_hidden_measures_and_invent_no_fault(take, fraction, seed, block):
    follower = follower_of(take)
    out = run(take, sv.null_frames(follower, empty_indexes(len(follower["frames"]), fraction, seed, block)))
    assert (out["value"], out["grade"], out["faults"], out["warnings"]) == (100, "A", [], [])


@PROPERTY
@given(take=st.sampled_from(CORRECT), fraction=st.floats(0.6, 1.0), seed=st.integers(0, 2 ** 16), block=st.booleans())
def test_p8_a_mostly_empty_take_is_no_usable_measures_with_no_fault(take, fraction, seed, block):
    follower = follower_of(take)
    out = run(take, sv.null_frames(follower, empty_indexes(len(follower["frames"]), fraction, seed, block)))
    assert "no_usable_measures" in out["warnings"] and out["faults"] == []
    assert out["value"] <= score.WARNING_CAP and out["grade"] == "F"
