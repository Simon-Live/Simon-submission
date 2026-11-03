"""Silhouette keyframes and SAM mask parsing. These do not call the Meta API."""

import unittest

import numpy as np

from keyframe_finder.mask_motion import (
    ERROR_RATIO,
    SHAPE,
    find_mask_repetitions,
    keep_aspect,
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
    def test_down_and_up_is_one_repetition(self):
        found = find_mask_repetitions(_squat(), 8, ["start", "bottom", "top"])
        self.assertEqual(len(found), 1)
        start, bottom, top = [item["frame"] for item in found[0]["keyframes"]]
        self.assertEqual(start, 8)
        self.assertGreaterEqual(bottom, 14)
        self.assertLessEqual(bottom, 21)
        self.assertEqual(top, 27)
        self.assertEqual([item["name"] for item in found[0]["keyframes"]], ["start", "bottom", "top"])

    def test_two_squats_are_two_repetitions(self):
        masks = _squat() + _squat()[8:]
        found = find_mask_repetitions(masks, 8, ["start", "bottom", "top"])
        self.assertEqual(len(found), 2)
        self.assertLess(found[0]["keyframes"][-1]["frame"], found[1]["keyframes"][0]["frame"])

    def test_a_repetition_cut_off_by_the_clip_end_counts_once_held(self):
        down = [_pose(top) for top in (2, 8, 14, 20, 26, 32)]
        held = [_pose(2)] * 8 + down + [_pose(32)] * 8
        found = find_mask_repetitions(held, 8, ["start", "bottom", "top"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["keyframes"][-1]["frame"], len(held) - 1)
        cut = [_pose(2)] * 8 + down + [_pose(32)] * 2
        self.assertEqual(find_mask_repetitions(cut, 8, ["start", "bottom", "top"]), [])

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

    def test_a_one_way_drift_is_not_chopped_into_repetitions(self):
        masks = [_pose(min(2 + index, 36)) for index in range(36)]
        self.assertEqual(find_mask_repetitions(masks, 8, ["start", "bottom", "top"]), [])

    def test_box_proportions_tell_bent_from_upright(self):
        body = np.ones((SHAPE, SHAPE), dtype=bool)
        upright = keep_aspect(body, 40, 100)
        bent = keep_aspect(body, 70, 100)
        self.assertEqual(mask_distance(body, body), 0.0)
        self.assertGreater(mask_distance(upright, bent), ERROR_RATIO)

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

    def test_knee_lifts_are_found_while_the_person_drifts_sideways(self):
        # TICKET-380: a trainer drifting 18% of the frame one way while lifting their knees. The drift used to be the
        # biggest change, so the signal followed it and found no repetition.
        stand, lift = _pose(8), _pose(20)
        masks, centers = [], []
        for rep in range(4):
            for index in range(8):
                masks.append(stand if index < 4 else lift)
        for index in range(len(masks)):
            centers.append((0.40 + 0.18 * index / (len(masks) - 1), 0.50))
        found = find_mask_repetitions(masks, 8, ["start", "bottom", "top"], centers)
        self.assertGreaterEqual(len(found), 3)

    def test_a_drift_alone_is_still_not_a_repetition(self):
        pose = _pose(8)
        masks = [pose] * 32
        centers = [(0.30 + 0.30 * index / 31, 0.50) for index in range(32)]
        self.assertEqual(find_mask_repetitions(masks, 8, ["start", "bottom", "top"], centers), [])

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

    def test_someone_standing_far_behind_is_dropped(self):
        grid = _pose(8)
        person = _view(1, list(range(0, 40)), 0.26, (0.55, 0.50), 40, grid)
        behind = _view(2, list(range(0, 40)), 0.08, (0.42, 0.45), 40, grid)
        partner = _view(3, list(range(0, 40)), 0.11, (0.20, 0.45), 40, grid)
        kept = keep_exercisers([person, behind, partner], 15)
        self.assertEqual([view["id"] for view in kept], [1, 3])


if __name__ == "__main__":
    unittest.main()
