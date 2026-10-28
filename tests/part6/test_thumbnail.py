"""part6/thumbnail.py: a small two-colour front-view drawing of the middle frame of a normalized
animation (AC-F12, AC-C13)."""
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from part6 import formats, motion, processor, thumbnail

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "fixtures" / "output" / "catalog"
# sha256 of the six Phase 1 thumbnails, taken before the thumbnail read normalized animations.
PHASE1_SHA256 = {
    "arm-wave": "164cc2723610b7ea41e26ad47480f8dd87202ab7f12017ab92585960618d82f3",
    "forward-lunge": "4f5e8c9c297651e32254c3e5be285502061403f9d19f7c58747d5362bc35d14c",
    "hip-twist": "33ddfdcd1ab637de14508945c7bd8ea59d710e60e98b7858a1e370c9bdc0751a",
    "jumping-jack": "8e1460f0ce99be9fb3f3ebc9105557d90f629c830533a724fa90d2738c4dcc3e",
    "side-step": "37410393133ce11b779937568f27fc330553abf133fdaa678dd0fd5f0fe29b72",
    "squat": "f3c1004d86526c706abc02f414e48a01d473f0cf3d412b1f4169fa6323841f7d",
}


def animation():
    made = processor.generate("jumping-jack", 2000, motion.MotionParams(1.0, 2))["animation"]
    return formats.read_animation(made)


def numbers(svg, attr):
    return [float(v) for v in re.findall(rf'{attr}="([-0-9.]+)"', svg)]


def test_sixteen_bones_seventeen_joints_two_colours():
    svg = thumbnail.svg(animation())
    assert svg.count("<line") == 16 and svg.count("<circle") == 17
    assert set(re.findall(r'(?:stroke|fill)="(#[0-9a-f]{6})"', svg)) == {
        thumbnail.LEFT_COLOUR, thumbnail.RIGHT_COLOUR}


def test_transparent_background_and_no_text():
    svg = thumbnail.svg(animation())
    assert 'viewBox="0 0 160 160"' in svg
    for tag in ("<rect", "<text", "<title", "<image", "<style", "<script"):
        assert tag not in svg


def test_fits_the_viewbox_with_the_margin():
    svg = thumbnail.svg(animation())
    xs = numbers(svg, "cx") + numbers(svg, "x1") + numbers(svg, "x2")
    ys = numbers(svg, "cy") + numbers(svg, "y1") + numbers(svg, "y2")
    assert min(xs) >= 12 - 1e-6 and max(xs) <= 148 + 1e-6
    assert min(ys) >= 12 - 1e-6 and max(ys) <= 148 + 1e-6
    assert max(max(xs) - min(xs), max(ys) - min(ys)) > 130


def test_left_side_in_one_colour_right_side_in_the_other():
    svg = thumbnail.svg(animation())
    circles = re.findall(r'<circle cx="([-0-9.]+)" cy="[-0-9.]+" r="3" fill="(#[0-9a-f]{6})"', svg)
    by_colour = {}
    for x, colour in circles:
        by_colour.setdefault(colour, []).append(float(x))
    left, right = by_colour[thumbnail.LEFT_COLOUR], by_colour[thumbnail.RIGHT_COLOUR]
    assert len(left) == 9 and len(right) == 8
    assert min(left[1:]) > max(right)    # the subject's left (+x) is drawn to the right


def test_deterministic_and_uses_the_middle_frame():
    anim = animation()
    assert thumbnail.svg(anim) == thumbnail.svg(copy.deepcopy(anim))
    mid = len(anim["frames"]) // 2
    other = copy.deepcopy(anim)
    other["frames"][mid - 1]["joints"]["nose"][0] += 0.3
    other["frames"][0]["joints"]["nose"][0] += 0.3
    assert thumbnail.svg(other) == thumbnail.svg(anim)
    other["frames"][mid]["joints"]["left_wrist"][1] += 0.3
    assert thumbnail.svg(other) != thumbnail.svg(anim)


def test_a_frozen_pose_does_not_divide_by_zero():
    joints = {n: [0.0, 0.0, 0.0] for n in motion.JOINTS}
    flat = {"frames": [{"t": 0.0, "interpolated": False, "joints": joints}]}
    assert thumbnail.svg(flat).count("<circle") == 17


def test_joints_as_a_list_in_the_canonical_order_draw_the_same_picture():
    anim = animation()
    as_lists = copy.deepcopy(anim)
    for frame in as_lists["frames"]:
        frame["joints"] = [frame["joints"][n] for n in motion.JOINTS]
    assert thumbnail.svg(as_lists) == thumbnail.svg(anim)


def test_the_drawing_does_not_depend_on_the_order_of_the_joint_keys():
    anim = animation()
    shuffled = copy.deepcopy(anim)
    for frame in shuffled["frames"]:
        frame["joints"] = dict(reversed(list(frame["joints"].items())))
    assert thumbnail.svg(shuffled) == thumbnail.svg(anim)


def test_a_skeleton_played_as_an_animation_has_a_thumbnail():
    made = processor.generate("squat", 2000, motion.MotionParams(2.0, 1))["skeleton"]
    played = formats.playable(None, formats.read_skeleton(made))
    assert played["held"] is True
    assert thumbnail.svg(played).count("<line") == 16


def test_part4_animation_draws_the_same_way():
    data = (ROOT / "fixtures" / "part4" / "exercise" / "animation.json").read_bytes()
    svg = thumbnail.svg(formats.read_animation(json.loads(data)))
    assert svg.count("<line") == 16 and svg.count("<circle") == 17


@pytest.mark.parametrize("entry", sorted(PHASE1_SHA256))
def test_the_phase_1_thumbnails_come_out_byte_identical(entry):
    shipped = (CATALOG / entry / "thumbnail.svg").read_bytes()
    assert hashlib.sha256(shipped).hexdigest() == PHASE1_SHA256[entry]
    animation = formats.read_animation(json.loads(
        (CATALOG / entry / "animation.json").read_text()))
    assert thumbnail.svg(animation).encode() == shipped
