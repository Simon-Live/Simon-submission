"""part6/thumbnail.py: a small two-colour front-view drawing of the middle frame."""
import copy
import re

from part6 import motion, processor, thumbnail


def animation():
    return processor.generate("jumping-jack", 2000, motion.MotionParams(1.0, 2))["animation"]


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
    other["frames"][mid - 1]["people"][0]["joints"]["nose"]["x"] += 0.3
    other["frames"][0]["people"][0]["joints"]["nose"]["x"] += 0.3
    assert thumbnail.svg(other) == thumbnail.svg(anim)
    other["frames"][mid]["people"][0]["joints"]["left_wrist"]["y"] += 0.3
    assert thumbnail.svg(other) != thumbnail.svg(anim)


def test_a_frozen_pose_does_not_divide_by_zero():
    joints = {n: {"x": 0.0, "y": 0.0, "z": 0.0, "conf": 1.0} for n in motion.JOINTS}
    flat = {"frames": [{"people": [{"joints": joints}]}]}
    assert thumbnail.svg(flat).count("<circle") == 17
