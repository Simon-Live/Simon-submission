from types import SimpleNamespace as F

import pytest

from part5.detect import generic
from part5.measures import MEASURES
from part5.words import PHRASES, describe, phrase

GENERIC = {generic(m)[0]: generic(m)[1] for m in MEASURES}


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
