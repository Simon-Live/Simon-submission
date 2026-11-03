"""Tests from the client team's serverless-modal branch (moalborati/simon 7f24216, fdd331c) that apply to this tree: the
resampled tracks cover exactly the frames Part 2 samples. The route tests of that branch (deploy/serverless/) are not
in this tree."""

from __future__ import annotations


def test_resampled_tracks_cover_exactly_the_frames_part2_samples():
    """Part 2 refuses tracks with more or fewer frames than it samples (its `_check_same_frames`); the resampled
    file follows Part 2's own nearest-frame rule, so a 10 s, 30 fps clip at 5 fps gives 51 frames (the 10.0 s step
    takes the last frame, 9.967 s), not the 52 the old range wrote (#62)."""
    from part7 import track_resample

    pts = [i / 30 for i in range(300)]  # 10 s at 30 fps, last frame at 9.967 s
    times = track_resample.sample_times(pts, 5)
    assert len(times) == 51 and times[0] == 0.0 and abs(times[-1] - 299 / 30) < 1e-6
    doc = {"frames": [{"frame": n, "people": [{"id": 0, "bbox": [10, 10, 50, 100], "mask_rle": {"size": [1, 1], "counts": "a"},
                                               "confidence": 0.9}]} for n in range(30)]}  # tracked at 3 fps
    out = track_resample.resample(doc, 3, 5, 10.0, None, times)
    assert [f["frame"] for f in out["frames"]] == list(range(51))
