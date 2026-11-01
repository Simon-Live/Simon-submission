from types import SimpleNamespace as F

import pytest

from part5.detect import generic
from part5.lateral import lateral_for
from part5.measures import ALL_SPECS
from part5.words import PHRASES, describe, phrase
from part5.words import describe_timed, phrase_timed

GENERIC = {generic(m)[0]: generic(m)[1] for m in ALL_SPECS}   # body and foot measures (ADR-0015)


def fault(measure, direction, side, mag=20.0, thr=10.0):
    return F(measure=measure, direction=direction, side=side, magnitude_deg=mag, threshold_deg=thr)


def test_every_measure_and_direction_has_a_phrase():
    assert set(PHRASES) == set(GENERIC)
    for m, side in GENERIC.items():
        for d in ("more", "less"):
            sides = ["center"] if side == "center" else ["left", "right", "both"]
            for s in sides:
                assert phrase(m, d, s)


@pytest.mark.parametrize("m", [m for m, s in GENERIC.items() if s != "center"])
@pytest.mark.parametrize("d", ["more", "less"])
def test_phrase_names_the_right_side_only(m, d):
    assert phrase(m, d, "left").startswith("left ") and "right" not in phrase(m, d, "left")
    assert phrase(m, d, "right").startswith("right ") and "left" not in phrase(m, d, "right")
    both = phrase(m, d, "both")
    assert "left" not in both and "right" not in both


@pytest.mark.parametrize("m", list(PHRASES))
def test_more_and_less_say_different_things(m):
    for s in (["center"] if GENERIC[m] == "center" else ["left", "both"]):
        assert phrase(m, "more", s) != phrase(m, "less", s)


def test_readme_examples():
    assert phrase("foot_out", "more", "left") == "left foot too far out"
    assert phrase("upper_arm_out", "more", "both") == "elbows wider than the example"


@pytest.mark.parametrize("mag, foot, knee", [
    (12, "left foot slightly too far out", "left knee not quite bent enough"),
    (20, "left foot too far out", "left knee not bent enough"),
    (-35, "left foot much too far out", "left knee nowhere near bent enough"),
])
def test_size_qualifier_bands(mag, foot, knee):
    assert describe(fault("foot_out", "more", "left", mag)) == foot
    assert describe(fault("knee_flexion", "less", "left", mag)) == knee


def test_knee_valgus_phrases_read_as_the_spec_says():
    assert phrase("knee_valgus", "more", "left") == "left knee caving in"
    assert phrase("knee_valgus", "more", "right") == "right knee caving in"
    assert phrase("knee_valgus", "more", "both") == "knees caving in"
    assert phrase("knee_valgus", "less", "left") == "left knee pushed out"
    assert phrase("knee_valgus", "less", "both") == "knees pushed out"


@pytest.mark.parametrize("mag, text", [
    (9, "left knee caving in slightly"),
    (14, "left knee caving in"),
    (30, "left knee caving in a lot"),
])
def test_knee_valgus_size_qualifier_goes_after_the_verb(mag, text):
    assert describe(fault("knee_valgus", "more", "left", mag, thr=8.0)) == text
    assert describe(fault("knee_valgus", "more", "left", mag, thr=8.0), qualify=False) == "left knee caving in"


def test_qualifier_on_centre_and_plural():
    assert describe(fault("trunk_lean_forward", "more", "center", 12)) == "leaning forward slightly more than the example"
    assert describe(fault("upper_arm_out", "more", "both", 40)) == "elbows much wider than the example"
    assert describe(fault("upper_arm_out", "more", "both", 40), qualify=False) == "elbows wider than the example"


def test_every_phrase_reads_cleanly_in_every_band():
    for m, side in GENERIC.items():
        for d in ("more", "less"):
            for s in (["center"] if side == "center" else ["left", "both"]):
                for size in ("slight", "plain", "much"):
                    t = phrase(m, d, s, size)
                    assert "{" not in t and "  " not in t and t == t.strip(), t
                    assert "not slightly" not in t and "not much" not in t, t


def test_bad_side_is_an_error():
    with pytest.raises(ValueError):
        phrase("trunk_lean_forward", "more", "left")
    with pytest.raises(ValueError):
        phrase("knee_flexion", "less", "center")


@pytest.mark.parametrize("measure", ["trunk_lean_forward", "trunk_lean_side", "shoulder_tilt", "head_forward"])
def test_centre_phrases_are_relative_to_the_example(measure):
    # Detection only sees follower − expected, so these can't claim an absolute lean or tilt.
    for d in ("more", "less"):
        assert "the example" in phrase(measure, d, "center")


def every_phrase_case():
    for m, side in GENERIC.items():
        for d in ("more", "less"):
            for s in (["center"] if side == "center" else ["left", "right", "both"]):
                yield m, d, s


def test_phrase_timed_is_what_describe_timed_says_at_every_size():
    """`describe_timed` is `phrase_timed` at the size the fault's magnitude gives (the picker uses `phrase_timed`, WR9)."""
    sizes = {"slight": 12.0, "plain": 20.0, "much": 35.0}     # magnitudes against a threshold of 10
    cases = list(every_phrase_case())
    assert len(cases) > 60
    for m, d, s in cases:
        for size, mag in sizes.items():
            assert describe_timed(fault(m, d, s, mag)) == phrase_timed(m, d, s, size), (m, d, s, size)
        assert describe_timed(fault(m, d, s, 12.0), qualify=False) == phrase_timed(m, d, s)


def test_phrase_timed_derives_the_lateral_from_the_side_and_direction_as_the_analysis_does():
    for m in ("foot_out", "thigh_out", "upper_arm_out", "forearm_out"):
        for d in ("more", "less"):
            for s in ("left", "right"):
                lateral = lateral_for(m, d, s)
                assert lateral in ("left", "right")
                assert phrase_timed(m, d, s).endswith(f"too far {lateral}"), (m, d, s)
    assert phrase_timed("foot_out", "more", "right") == "right foot too far right"      # the label says "too far out"
    assert phrase_timed("foot_out", "less", "right") == "right foot too far left"
    assert phrase_timed("foot_out", "more", "both") == "feet too far apart"             # no side, no lateral
    assert phrase_timed("upper_arm_forward", "less", "left") == "left arm too low"
    with pytest.raises(KeyError):
        phrase_timed("ankle_lateral_offset", "more", "both")                             # a measure it has no words for
    with pytest.raises(ValueError):
        phrase_timed("knee_flexion", "less", "center")
