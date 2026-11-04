"""Local checks for the quality gate. These do not call the Meta API."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from keyframe_finder import from_video
from keyframe_finder.quality import _parse_stats, assess, measure
from keyframe_finder.signal import encode_rgb, ffmpeg_exe


def _clip(path, frames, fps=24):
    encode_rgb(path, frames, fps)


def _moving_body(ground, body, shift=6):
    frames = np.full((48, 360, 640, 3), ground, np.uint8)
    color = np.array(body, dtype=np.uint8)
    for index in range(frames.shape[0]):
        top = 80 + (index % 8) * shift
        frames[index, top : top + 150, 220:340] = color
    return frames


class QualityGateTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_bright_clip_needs_no_enhancement(self):
        path = self.root / "bright.mp4"
        _clip(path, _moving_body(170, (40, 40, 40)))
        decision = assess(path)
        self.assertEqual(decision.verdict, "fine", decision.message)
        self.assertEqual(decision.filters, [])
        self.assertEqual(decision.width, 640)

    def test_dark_body_is_enhanced_and_previewed(self):
        path = self.root / "dark.mp4"
        _clip(path, _moving_body(12, (110, 100, 90), shift=4))
        decision = assess(path)
        self.assertEqual(decision.verdict, "enhanced", decision.message)
        self.assertEqual(decision.width, 960)
        self.assertTrue(any(item.startswith("eq=") for item in decision.filters))
        self.assertTrue(any(item.startswith("hqdn3d=") for item in decision.filters))
        self.assertIsNotNone(decision.preview)
        self.assertGreater(decision.preview.yavg, decision.measurement.yavg)
        dest = self.root / "analysis.mp4"
        from_video.transcode(
            path, dest, 8, decision.width, decision.filtergraph, decision.crf
        )
        lifted = measure(dest)
        self.assertGreater(lifted.yavg, decision.measurement.yavg + 10)

    def test_flat_clip_is_refused(self):
        path = self.root / "flat.mp4"
        frames = np.full((48, 360, 640, 3), 8, np.uint8)
        _clip(path, frames)
        decision = assess(path)
        self.assertEqual(decision.verdict, "refused")
        self.assertIn("No API call was made", decision.message)
        self.assertIn("spread", decision.message)

    def test_blurred_clip_is_refused(self):
        path = self.root / "sharp.mp4"
        blurred = self.root / "blurred.mp4"
        _clip(path, _moving_body(170, (30, 30, 30)))
        import subprocess

        subprocess.check_call(
            [
                ffmpeg_exe(),
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vf",
                "gblur=sigma=12",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(blurred),
            ]
        )
        decision = assess(blurred)
        self.assertEqual(decision.verdict, "refused", decision.message)
        self.assertIn("blurred", decision.message)

    def test_still_picture_is_refused(self):
        path = self.root / "still.mp4"
        frame = np.full((360, 640, 3), 150, np.uint8)
        frame[100:250, 250:360] = 30
        _clip(path, np.broadcast_to(frame, (48, 360, 640, 3)).copy())
        decision = assess(path)
        self.assertEqual(decision.verdict, "refused", decision.message)
        self.assertIn("does not change", decision.message)

    def test_tiny_picture_is_refused(self):
        path = self.root / "tiny.mp4"
        frames = np.full((16, 80, 80, 3), 140, np.uint8)
        frames[:, 20:50, 30:55] = 20
        _clip(path, frames)
        decision = assess(path)
        self.assertEqual(decision.verdict, "refused")
        self.assertIn("80×80", decision.message)
        self.assertIn("No API call was made", decision.message)

    def test_refused_video_is_not_uploaded(self):
        path = self.root / "flat.mp4"
        _clip(path, np.full((48, 360, 640, 3), 8, np.uint8))
        calls = []
        original = from_video.upload_video
        from_video.upload_video = lambda *args, **kwargs: calls.append(args)
        try:
            result = from_video.process(path)
        finally:
            from_video.upload_video = original
        self.assertIsNone(result)
        self.assertEqual(calls, [])


class StatsParseTest(unittest.TestCase):
    def test_minus_nan_from_ffmpeg_is_read_as_missing(self):
        # Some ffmpeg builds print -nan for the blur of a flat frame.
        text = (
            "[Parsed_metadata_7 @ 0x1] frame:0    pts:0       pts_time:0\n"
            "[Parsed_metadata_7 @ 0x1] lavfi.signalstats.YAVG=8.0\n"
            "[Parsed_metadata_7 @ 0x1] lavfi.blur=-nan\n"
        )
        frames = _parse_stats(text)
        self.assertEqual(frames[0]["signalstats.YAVG"], 8.0)
        self.assertTrue(np.isnan(frames[0]["blur"]))


if __name__ == "__main__":
    unittest.main()
