"""The second opinion's masked-part rule reads words, and now more of them (TICKET-098, docs/specs/second-opinion.md AC-SO-04).

The cases are the 1.14.0 delta review's probes (progress/review-20261102-consolidated-114.md, residual 1): with a seated
mask a note on the lower body, the lap, the kneecap or the tibia was shown, and with `left_leg` masked a note that named
the masked side with no part noun ("while the left lifts") was shown. No model call: `guard` is run on sentences.
"""
import json

import pytest

from part5.mask import parse_mask
from part5.opinion import guard
from part5.phrasing.template import GROUP_RX

SIDED = [group for group in GROUP_RX if group not in ("head", "trunk")]
SHOWS = {**{group: {"left", "right"} for group in SIDED}, "head": {"any"}, "trunk": {"any"}}


def problem(text, mask=None, shows=None, masked=None):
    if mask:
        masked = guard.masked_parts(parse_mask(mask).block())
    return guard.text_problem(text, 5.0, SHOWS if shows is None else shows, masked)


def part_reason(group):
    return f"names a body part not scored in this take ({group})"


@pytest.mark.parametrize("text, group", [
    ("Your lower body stays quiet through the take.", "thigh"),
    ("Your lap stays still and the trunk leans forward.", "thigh"),
    ("The lower limbs sway.", "thigh"),
    ("The lower extremities stay still.", "thigh"),
    # R3 of the 1.14.1 review: a hyphen or a second space between the two words was not the listed phrase
    ("Your lower-body stays quiet through the take.", "thigh"),
    ("Your lower  body stays quiet through the take.", "thigh"),
    ("Your lower\u00a0body stays quiet through the take.", "thigh"),
    ("The lower-limbs sway.", "thigh"),
    ("The lower  extremities stay still.", "thigh"),
    ("The femur rotates.", "thigh"),
    ("The kneecap tracks well.", "knee"),
    ("The knee-caps move.", "knee"),
    ("The patella moves.", "knee"),
    ("The tibia rotates.", "knee"),
    ("Your footwork stays tidy.", "foot"),
    ("The pelvic tilt is small.", "hip"),
    ("Your tailbone stays down.", "hip"),
])
def test_ac_so_04_a_seated_take_refuses_the_words_the_review_found_for_the_legs(text, group):
    assert problem(text, "seated") == part_reason(group)
    assert problem(text) is None   # the camera shows every part, so without the mask the note is shown


@pytest.mark.parametrize("text", [
    "The trunk leans forward and the head drops.", "Your shoulders stay level.", "The overlap of the arms is small.",
    "The hands clap together.", "Their left arm stays level.", "The elbows bend more than the recording.",
])
def test_ac_so_04_a_seated_take_still_shows_a_note_on_what_it_scores(text):
    assert problem(text, "seated") is None


@pytest.mark.parametrize("text, group", [
    ("The lower body stays still.", "thigh"), ("The lap stays still.", "thigh"), ("The kneecap moves.", "knee"),
    ("The tibia rotates.", "knee"), ("The femur rotates.", "thigh"), ("The lower limbs sway.", "thigh"),
])
def test_ac_so_04_the_new_words_need_the_part_to_be_shown_without_a_mask(text, group):
    shown = {key: value for key, value in SHOWS.items() if key != group}
    assert problem(text, shows=shown) == f"names a body part the clip does not show ({group})"
    assert problem(text) is None


@pytest.mark.parametrize("text, reason", [
    ("The right foot stays planted while the left lifts.", part_reason("foot")),
    ("The right knee stays firm and the left one bends.", part_reason("knee")),
    ("Your right foot is steady, and so is your left.", part_reason("foot")),
    ("Both legs stay still.", part_reason("thigh")),
    ("The right foot stays planted while the left foot lifts.", part_reason("foot")),
    ("The right leg is steady.", None),
    ("Your weight shifts onto the right side.", None),
    ("The right foot steps out to the right.", None),
    ("The right foot steps out to the left.", None),
    ("The right foot stays out towards the left.", None),
    ("The left hand drifts right.", None),
    ("The head turns left.", None),
    ("The left shoulder drops a little.", None),
    ("The right hip drops while the left shoulder rises.", None),
    ("The right knee stays firm and the left arm swings.", None),
])
def test_ac_so_04_one_masked_leg_refuses_a_bare_side_word_that_stands_for_that_leg(text, reason):
    assert problem(text, "left_leg") == reason
    assert problem(text) is None   # without the mask each one is shown


def test_ac_so_04_the_other_leg_is_masked_the_other_way_round():
    assert problem("The left foot stays planted while the right lifts.", "right_leg") == part_reason("foot")
    assert problem("The right foot stays planted while the left lifts.", "right_leg") == part_reason("foot")
    assert problem("The left knee stays firm and the right arm swings.", "right_leg") is None


@pytest.mark.parametrize("text, side", [
    ("Your left side stays quiet.", "left"), ("The left stays still.", "left"), ("Their left lifts.", "left"),
])
def test_ac_so_04_a_side_with_every_part_masked_is_refused_with_no_part_noun(text, side):
    masked = {group: {"left"} for group in SIDED}
    assert problem(text, masked=masked) == f"names a side not scored in this take ({side})"
    assert problem(text.replace("left", "right"), masked=masked) is None   # the other side is scored
    assert problem(text) is None


def test_ac_so_04_a_side_with_one_part_scored_is_not_refused_for_a_bare_side_word():
    """The limit, as the spec says it: `left_leg` leaves the left shoulder and arm scored, so "your left side" is not
    a masked part; and a paraphrase that names no listed word passes."""
    assert problem("Their left side leans.", "left_leg") is None
    assert problem("Your left side stays quiet.", "seated") is None
    assert problem("Your stance is wide and your steps are even.", "seated") is None
    assert problem("The lower half stays still.", "seated") is None


def test_ac_so_04_a_dropped_note_is_listed_with_its_reason():
    masked = guard.masked_parts(parse_mask("seated").block())
    text = json.dumps({"verdicts": [{"fault_index": 0, "agrees": True, "note": "Your lower body stays quiet."},
                                    {"fault_index": 1, "agrees": False, "note": "The elbows bend more."}],
                       "observations": [{"at_s": 1.0, "text": "The kneecap tracks well."},
                                        {"at_s": 2.0, "text": "The shoulders stay level."}]})
    found = guard.read_answer(text, 2, 5.0, SHOWS, masked)
    assert [v["fault_index"] for v in found["verdicts"]] == [1]
    assert [o["text"] for o in found["observations"]] == ["The shoulders stay level."]
    assert found["rejected"] == [{"kind": "verdict", "index": 0, "reason": part_reason("thigh")},
                                 {"kind": "observation", "index": 0, "reason": part_reason("knee")}]
