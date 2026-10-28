"""Saved-run rebuild and Spark name recovery. These do not call the Meta API."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from keyframe_finder import from_video
from keyframe_finder.mask_motion import SHAPE

# Spark's real answer on one clip: the second section is missing its "{".
BROKEN = (
    '{"sections":[{"movement":"intro_groove","start_s":0,"end_s":5.0,'
    '"phase_names":["hands_pressed","hands_open","hands_on_chest"]},'
    '"movement":"side_step_point","start_s":5.0,"end_s":9.8,'
    '"phase_names":["stance_center","leg_extended","arm_pointed"]},'
    '{"movement":"pull_down_bounce","start_s":9.8,"end_s":13.5,'
    '"phase_names":["upright_stance","forward_bend","arms_pulled_down"]}]}'
)


def _pose(top):
    grid = np.zeros((SHAPE, SHAPE), dtype=bool)
    grid[top : top + 10, 18:30] = True
    return grid


def _tracks():
    tops = [2] * 8 + [2, 8, 14, 20, 26, 32] + [32] * 8 + [32, 26, 20, 14, 8, 2] + [2] * 8
    samples = []
    for frame, top in enumerate(tops):
        samples.append(
            {
                "frame": frame,
                "x1": 200.0,
                "y1": 100.0,
                "x2": 440.0,
                "y2": 420.0,
                "frame_w": 640.0,
                "frame_h": 480.0,
                "c": 0.9 if frame % 2 else None,
                "grid": None if frame == 3 else _pose(top),
            }
        )
    return {7: samples}


def _run(frames):
    return {
        "version": from_video.SAVED_VERSION,
        "video": "inbox/clip.mp4",
        "source_fps": 30.0,
        "analysis_fps": 8.0,
        "frames": frames,
        "width": 640,
        "height": 480,
        "duration_s": frames / 8.0,
        "quality": {"verdict": "fine"},
    }


class SparkSectionsTest(unittest.TestCase):
    def test_one_broken_bracket_keeps_every_section(self):
        sections = from_video.parse_sections(BROKEN, 16.5)
        self.assertEqual(
            [section["movement"] for section in sections],
            ["intro_groove", "side_step_point", "pull_down_bounce"],
        )
        self.assertEqual(sections[1]["phase_names"], ["stance_center", "leg_extended", "arm_pointed"])
        self.assertEqual(sections[1]["start_s"], 5.0)
        self.assertTrue(all(section["source"] == "spark" for section in sections))

    def test_clean_json_is_read_as_is(self):
        text = json.dumps(
            {"sections": [{"movement": "squat", "start_s": 0, "end_s": 4, "phase_names": ["start", "bottom", "top"]}]}
        )
        sections = from_video.parse_sections(text, 4.0)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["movement"], "squat")

    def test_nothing_readable_falls_back(self):
        for text in ("", "no json here", '{"sections": "oops"}'):
            sections = from_video.parse_sections(text, 10.0)
            self.assertEqual(len(sections), 1)
            self.assertEqual(sections[0]["source"], "fallback")
            self.assertEqual(sections[0]["phase_names"], ["start", "bottom", "top"])


def _section(movement, start_s, end_s):
    return {"movement": movement, "start_s": start_s, "end_s": end_s, "phase_names": ["a", "b", "c"]}


def _box(frame, x1, y1, x2, y2):
    return {"frame": frame, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "frame_w": 100.0, "frame_h": 100.0, "c": 0.9, "grid": None}


class SectionTest(unittest.TestCase):
    def test_one_movement_is_one_range(self):
        sections = [_section("fly", 0, 2.6), _section("fly", 2.6, 5.3)]
        self.assertEqual(from_video.movement_spans(sections, 15, 80), [(0, 80)])

    def test_each_new_movement_starts_a_range(self):
        sections = [_section("intro", 0, 5), _section("punch", 5, 11), _section("punch", 11, 12), _section("bounce", 12, 16)]
        self.assertEqual(from_video.movement_spans(sections, 10, 160), [(0, 50), (50, 120), (120, 160)])

    def test_a_repetition_belongs_to_the_range_of_its_middle(self):
        tops = [2] * 8 + [2, 8, 14, 20, 26, 32] + [32] * 8 + [32, 26, 20, 14, 8, 2] + [2] * 8
        grids = [_pose(top) for top in tops]
        whole = from_video.motion_bounds_by_span(grids, None, 8, [(0, len(grids))])
        self.assertEqual(len(whole), 1)
        middle = whole[0][1]
        split = from_video.motion_bounds_by_span(grids, None, 8, [(0, middle + 1), (middle + 1, len(grids))])
        self.assertEqual(split, whole)

    def test_a_box_inside_a_bigger_person_is_dropped_on_that_frame(self):
        tracks = {
            1: [_box(0, 20, 10, 60, 95), _box(1, 20, 10, 60, 95)],
            2: [_box(0, 30, 70, 45, 92), _box(1, 70, 30, 90, 92)],
        }
        kept = from_video.drop_parts(tracks)
        self.assertEqual(len(kept[1]), 2)
        self.assertEqual([sample["frame"] for sample in kept[2]], [1])


class SavedRunTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.saved_root = from_video.ROOT
        self.saved_upload = from_video.upload_video
        from_video.ROOT = self.root

        def refuse(*args, **kwargs):
            raise AssertionError("a rebuild must not upload")

        from_video.upload_video = refuse

    def tearDown(self):
        from_video.ROOT = self.saved_root
        from_video.upload_video = self.saved_upload
        self.directory.cleanup()

    def test_tracks_survive_a_save_and_load(self):
        tracks = _tracks()
        path = self.root / "tracks.npz"
        from_video.save_tracks(path, tracks)
        loaded = from_video.load_tracks(path)
        self.assertEqual(list(loaded), [7])
        for before, after in zip(tracks[7], loaded[7]):
            for field in ("frame", "x1", "y1", "x2", "y2", "frame_w", "frame_h", "c"):
                self.assertEqual(before[field], after[field])
            if before["grid"] is None:
                self.assertIsNone(after["grid"])
            else:
                self.assertTrue(np.array_equal(before["grid"], after["grid"]))

    def test_rebuild_matches_the_live_run_without_the_api(self):
        tracks = _tracks()
        frames = len(tracks[7])
        run = _run(frames)
        spark = json.dumps(
            {"sections": [{"movement": "squat", "start_s": 0, "end_s": frames / 8.0, "phase_names": ["start", "bottom", "top"]}]}
        )
        live = from_video.build_document(run, tracks, spark)

        run_path, tracks_path, spark_path = from_video.saved_paths("clip")
        run_path.parent.mkdir(parents=True)
        run_path.write_text(json.dumps(run), encoding="utf-8")
        from_video.save_tracks(tracks_path, tracks)
        spark_path.write_text(spark, encoding="utf-8")

        dest = from_video.process(self.root / "inbox" / "clip.mp4")
        rebuilt = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt, json.loads(json.dumps(live)))
        self.assertEqual(rebuilt["spark_names"], "spark")
        self.assertGreater(sum(len(person["repetitions"]) for person in rebuilt["people"]), 0)

    def test_an_incomplete_or_old_save_is_not_reused(self):
        run_path, tracks_path, spark_path = from_video.saved_paths("clip")
        run_path.parent.mkdir(parents=True)
        from_video.save_tracks(tracks_path, _tracks())
        spark_path.write_text("", encoding="utf-8")
        self.assertIsNone(from_video.rebuild(self.root / "clip.mp4"))
        old = _run(10)
        old["version"] = 0
        run_path.write_text(json.dumps(old), encoding="utf-8")
        self.assertIsNone(from_video.rebuild(self.root / "clip.mp4"))


if __name__ == "__main__":
    unittest.main()
