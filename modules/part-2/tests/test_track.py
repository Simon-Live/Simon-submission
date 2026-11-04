import json

import pytest

from part2.schema import validate_tracks
from part2.track import build_tracks, derive_fps, mask_to_rle, parse_sam31_text, rle_counts, track

MASK_A = [[1, 1, 0], [0, 1, 0], [0, 0, 0]]  # 3x3
MASK_B = [[0, 0], [1, 1]]  # 2x2


def _decode(rle):
    h, w = rle["size"]
    flat = []
    val = 0
    for c in rle_counts(rle):
        flat.extend([val] * c)
        val = 1 - val
    assert len(flat) == h * w
    return [[flat[x * h + y] for x in range(w)] for y in range(h)]


def test_mask_to_rle_roundtrips():
    for m in (MASK_A, MASK_B, [[0, 0], [0, 0]], [[1]]):
        rle = mask_to_rle(m)
        assert rle["size"] == [len(m), len(m[0])]
        assert _decode(rle) == m


def test_mask_to_rle_rejects_ragged_and_empty():
    with pytest.raises(ValueError, match="same width"):
        mask_to_rle([[1, 0], [1]])
    with pytest.raises(ValueError, match="non-empty"):
        mask_to_rle([])


def _recs():
    return [{"frame": 0, "t_ms": 0.0, "file": "000000.jpg"},
            {"frame": 2, "t_ms": 66.7, "file": "000002.jpg"}]  # gap: frame 1 dropped


def test_build_tracks_keeps_frames_ids_and_gaps():
    dets = {0: [{"id": 2, "bbox": [1, 2, 3, 4], "mask": MASK_A, "confidence": 0.9},
                {"id": 1, "bbox": [0, 0, 2, 2], "mask": MASK_B, "confidence": 0.8}],
            "2": []}  # string frame key, as from JSON
    doc = build_tracks(_recs(), dets)
    validate_tracks(doc)
    assert [f["frame"] for f in doc["frames"]] == [0, 2]
    assert [p["id"] for p in doc["frames"][0]["people"]] == [1, 2]  # sorted by id
    assert doc["frames"][1]["people"] == []
    p = doc["frames"][0]["people"][1]
    assert p["bbox"] == [1.0, 2.0, 3.0, 4.0] and p["confidence"] == 0.9
    assert _decode(p["mask_rle"]) == MASK_A


def test_track_writes_valid_json_with_fake_tracker(tmp_path):
    (tmp_path / "frames.json").write_text(json.dumps({"source": "x", "frames": _recs()}))

    def fake(frames_dir, recs):
        assert list(recs) == _recs()
        return {0: [{"id": 1, "bbox": [0, 0, 2, 2], "mask": MASK_B, "confidence": 0.5}]}

    doc = track(tmp_path, tmp_path / "out" / "tracks.json", tracker=fake)
    written = json.loads((tmp_path / "out" / "tracks.json").read_text())
    assert written == doc
    validate_tracks(written)


def test_build_tracks_rejects_frames_not_in_records():
    with pytest.raises(ValueError, match="not in frames.json"):
        build_tracks(_recs(), {99: [{"id": 1, "bbox": [0, 0, 1, 1], "mask": MASK_B, "confidence": 0.5}]})


def test_mask_to_rle_large_mask_matches_counts():
    import numpy as np

    rng = np.random.default_rng(0)
    m = (rng.random((720, 1280)) > 0.5).astype(int)
    rle = mask_to_rle(m)
    flat = m.astype(bool).ravel(order="F")
    bounds = np.flatnonzero(np.diff(flat)) + 1
    counts = np.diff(np.concatenate(([0], bounds, [flat.size]))).astype(int).tolist()
    if flat[0]:
        counts.insert(0, 0)
    assert rle_counts(rle) == counts


def test_parse_sam31_text_maps_frames_boxes_and_masks():
    recs = [{"frame": 10, "t_ms": 0.0, "file": "a.jpg"}, {"frame": 12, "t_ms": 100.0, "file": "b.jpg"}]
    # one 4x3 image; object id 5, box (1,0)-(3,2), 2x2 crop mask [[1,0],[0,1]], score .9
    text = ("<0f>5<|box;x1=1;y1=0;x2=3;y2=2;w=4;h=3;c=0.9|>"
            "<|mask;x=0;y=0;c=0.9;data=2,2,~fake|>"
            "<1f>5<|box;x1=1;y1=0;x2=3;y2=2;w=4;h=3;c=0.8|>"
            "<|mask;x=0;y=0;c=0.8;data=2,2,~fake|>")

    def fake_decode(payload, w, h):
        assert (w, h) == (2, 2)
        return bytes([1, 0, 0, 1])

    dets = parse_sam31_text(text, recs, mask_decoder=fake_decode)
    assert sorted(dets) == [10, 12]  # API indices mapped onto real frame numbers
    d = dets[10][0]
    assert d["id"] == 5 and d["bbox"] == [1, 0, 2, 2] and d["confidence"] == 0.9
    assert _decode(d["mask_rle"]) == [[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 0]]
    doc = build_tracks(recs, dets)
    assert doc["frames"][0]["people"][0]["mask_rle"]["size"] == [3, 4]


def test_derive_fps_from_timestamps():
    recs = [{"frame": i, "t_ms": i * 40.0, "file": "x"} for i in range(5)]
    assert derive_fps(recs) == 25.0
    assert derive_fps(recs[:1]) == 30.0


def test_parse_sam31_rejects_missing_confidence_and_offsets():
    recs = [{"frame": 0, "t_ms": 0.0, "file": "a.jpg"}]
    dec = lambda payload, w, h: bytes([1] * (w * h))
    with pytest.raises(ValueError, match="no confidence"):
        parse_sam31_text("<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=2;h=2|>"
                         "<|mask;x=0;y=0;data=1,1,~f|>", recs, mask_decoder=dec)
    with pytest.raises(ValueError, match="mask offset"):
        parse_sam31_text("<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=2;h=2;c=0.5|>"
                         "<|mask;x=3;y=0;c=0.5;data=1,1,~f|>", recs, mask_decoder=dec)


def test_ffmpeg_exe_falls_back_to_imageio(monkeypatch):
    import part2.track as tr

    monkeypatch.setattr("shutil.which", lambda _: None)
    assert tr._ffmpeg_exe().endswith(("ffmpeg", "ffmpeg.exe")) or "ffmpeg" in tr._ffmpeg_exe()
