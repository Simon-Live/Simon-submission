"""Silhouette keyframes and SAM mask parsing. These do not call the Meta API."""

import unittest

import numpy as np

from keyframe_finder.mask_motion import (
    ERROR_RATIO,
    SHAPE,
    find_mask_repetitions,
    mask_distance,
)
from keyframe_finder.sam_parse import BoxParser
from keyframe_finder.from_video import keep_exercisers, stitch_tracks

# A known-good 5x5 one_bit payload from the SAM parser contract.
_PAYLOAD = "!!!!!(QO(0lu8?"


def _pose(top):
    grid = np.zeros((SHAPE, SHAPE), dtype=bool)
    grid[top : top + 10, 18:30] = True
    return grid


def _arms(up):
    grid = np.zeros((SHAPE, SHAPE), dtype=bool)
    grid[16:40, 20:28] = True
    grid[8:42, 6:10] = True
    grid[8:42, 38:42] = True
    if up:
        grid[8:18, 10:38] = True
    else:
        grid[32:42, 10:38] = True
    return grid


def _squat():
    masks = []
    for _ in range(8):
        masks.append(_pose(2))
    for top in (2, 8, 14, 20, 26, 32):
        masks.append(_pose(top))
    for _ in range(8):
        masks.append(_pose(32))
    for top in (32, 26, 20, 14, 8, 2):
        masks.append(_pose(top))
    for _ in range(8):
        masks.append(_pose(2))
    return masks


class MaskMotionTest(unittest.TestCase):
    def test_down_and_up_settles_twice(self):
        found = find_mask_repetitions(_squat(), 8, ["start", "bottom", "top"])
        self.assertEqual(len(found), 2)
        down = [item["frame"] for item in found[0]["keyframes"]]
        up = [item["frame"] for item in found[1]["keyframes"]]
        self.assertEqual(down[0], 8)
        self.assertEqual(down[2], 13)
        self.assertGreaterEqual(down[1], 10)
        self.assertLessEqual(down[1], 13)
        self.assertEqual(up[0], 22)
        self.assertEqual(up[2], 27)
        self.assertEqual([item["name"] for item in found[0]["keyframes"]], ["start", "bottom", "top"])

    def test_outline_wobble_is_not_a_move(self):
        base = _pose(4)
        masks = []
        for index in range(40):
            grid = base.copy()
            if index % 2:
                grid[4, 18] = False
            masks.append(grid)
        self.assertLess(mask_distance(masks[0], masks[1]), ERROR_RATIO)
        self.assertEqual(find_mask_repetitions(masks, 8, ["start", "bottom", "top"]), [])

    def test_motion_inside_one_box_is_a_keyframe(self):
        down = _arms(False)
        up = _arms(True)
        self.assertGreater(mask_distance(down, up), ERROR_RATIO)
        masks = [down] * 8 + [up] * 8 + [down] * 8
        found = find_mask_repetitions(masks, 8, ["start", "reach", "return"])
        self.assertGreaterEqual(len(found), 1)
        middle = found[0]["keyframes"][1]["frame"]
        self.assertGreaterEqual(middle, 8)
        self.assertLess(middle, 16)

    def test_five_poses_stay_in_order(self):
        found = find_mask_repetitions(_squat(), 8, ["a", "b", "c", "d", "e"])
        frames = [item["frame"] for item in found[0]["keyframes"]]
        self.assertEqual(len(frames), 5)
        self.assertEqual(frames, sorted(frames))
        self.assertEqual(len(set(frames)), 5)

    def test_continuous_motion_is_not_one_long_rep(self):
        masks = [_pose(min(2 + index, 36)) for index in range(36)]
        found = find_mask_repetitions(masks, 8, ["start", "bottom", "top"])
        self.assertGreater(len(found), 1)
        gaps = []
        for rep in found:
            frames = [item["frame"] for item in rep["keyframes"]]
            gaps.append(frames[-1] - frames[0])
        self.assertLess(max(gaps), len(masks) - 1)

    def test_small_move_counts_when_it_is_the_biggest_one(self):
        low = _pose(10)
        high = _pose(12)
        masks = [low] * 8 + [high] * 8
        self.assertLess(mask_distance(low, high), 0.40)
        found = find_mask_repetitions(masks, 8, ["start", "bottom", "top"])
        self.assertGreaterEqual(len(found), 1)

    def test_a_step_counts_when_the_shape_stays_the_same(self):
        pose = _pose(8)
        masks = [pose] * 24
        centers = [(0.20, 0.50)] * 8 + [(0.55, 0.50)] * 8 + [(0.20, 0.50)] * 8
        found = find_mask_repetitions(masks, 8, ["start", "bottom", "top"], centers)
        self.assertGreaterEqual(len(found), 1)

    def test_a_shivering_box_is_not_a_step(self):
        pose = _pose(8)
        masks = [pose] * 24
        centers = [(0.50, 0.50) if index % 2 == 0 else (0.51, 0.50) for index in range(24)]
        self.assertEqual(
            find_mask_repetitions(masks, 8, ["start", "bottom", "top"], centers),
            [],
        )


class SamParseTest(unittest.TestCase):
    def _record(self):
        return (
            "<0f>7<|box;x1=1;y1=2;x2=30;y2=40;w=100;h=80;c=0.91|>"
            f"<|mask;x=0;y=0;c=0.91;data=5,5,{_PAYLOAD}|>"
        )

    def test_mask_becomes_a_silhouette(self):
        parser = BoxParser()
        parser.feed(self._record())
        parser.finish()
        sample = parser.tracks[7][0]
        self.assertEqual(sample["frame"], 0)
        self.assertEqual(sample["x1"], 1.0)
        self.assertEqual(sample["c"], 0.91)
        self.assertEqual(sample["grid"].shape, (SHAPE, SHAPE))
        self.assertTrue(sample["grid"].any())

    def test_split_stream_still_parses(self):
        text = self._record()
        parser = BoxParser()
        parser.feed(text[:40])
        self.assertEqual(parser.tracks, {})
        parser.feed(text[40:])
        parser.finish()
        self.assertIn(7, parser.tracks)
        self.assertTrue(parser.tracks[7][0]["grid"].any())

    def test_box_without_a_mask_is_kept(self):
        parser = BoxParser()
        parser.feed("<3f>1<|box;x1=0;y1=0;x2=4;y2=5|>")
        parser.finish()
        sample = parser.tracks[1][0]
        self.assertEqual(sample["frame"], 3)
        self.assertIsNone(sample["grid"])
        self.assertIsNone(sample["c"])


def _view(object_id, frames, area, center, n_frames, grid):
    samples = []
    for frame in frames:
        samples.append(
            {
                "frame": frame,
                "x1": center[0] * 100 - 5,
                "y1": center[1] * 100 - 10,
                "x2": center[0] * 100 + 5,
                "y2": center[1] * 100 + 10,
                "frame_w": 100,
                "frame_h": 100,
                "c": 0.9,
                "grid": grid,
            }
        )
    return {
        "id": object_id,
        "samples": samples,
        "median_area": area,
        "first": min(frames),
        "last": max(frames),
        "width": 100,
        "height": 100,
        "n_frames": n_frames,
    }


class TrackTest(unittest.TestCase):
    def test_someone_who_leaves_and_returns_is_one_person(self):
        grid = _pose(8)
        first = _view(1, list(range(0, 16)), 0.20, (0.40, 0.50), 80, grid)
        second = _view(2, list(range(18, 40)), 0.20, (0.42, 0.50), 80, grid)
        merged = stitch_tracks([first, second], 8)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["id"], 1)
        self.assertEqual(merged[0]["last"], 39)

    def test_a_brief_tiny_figure_is_dropped(self):
        grid = _pose(8)
        person = _view(1, list(range(0, 40)), 0.20, (0.40, 0.50), 200, grid)
        passerby = _view(2, list(range(0, 8)), 0.20, (0.80, 0.20), 200, grid)
        mirror = _view(3, list(range(0, 40)), 0.03, (0.10, 0.50), 200, grid)
        kept = keep_exercisers(stitch_tracks([person, passerby, mirror], 15), 15)
        self.assertEqual([view["id"] for view in kept], [1])


if __name__ == "__main__":
    unittest.main()
