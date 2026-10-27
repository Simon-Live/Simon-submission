import json

import pytest

from part2.schema import validate_tracks
from part2.track import build_tracks, mask_to_rle, rle_counts, track

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
