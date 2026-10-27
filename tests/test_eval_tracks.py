import json

import pytest

from part2.eval_tracks import evaluate, evaluate_files, iou

FPS_MS = 1000.0  # 1 keyframe per second in the synthetic clips


def _clip(n_people=5, n_key=10, swap_at=None, drop=None, no_pose=()):
    """Perfect synthetic clip: GT person i stands at x=i*100; tracker agrees,
    except swap_at=(gt_id, keyframe_index) switches that person to a new track id,
    drop=(gt_id, keyframe_index) misses one keyframe, no_pose=gt ids without pose."""
    gt_frames, tr_frames, pose_frames = [], [], []
    for k in range(n_key):
        frame, t = k * 30, k * FPS_MS
        gt_p, tr_p, pose_p = [], [], []
        for i in range(n_people):
            box = [i * 100.0, 0.0, 50.0, 100.0]
            gt_p.append({"id": i + 1, "bbox": box})
            if drop == (i + 1, k):
                continue
            tid = i + 1
            if swap_at and swap_at[0] == i + 1 and k >= swap_at[1]:
                tid = 100 + i
            tr_p.append({"id": tid, "bbox": box, "mask_rle": {"size": [100, 50], "counts": "a"}, "confidence": 0.9})
            if i + 1 not in no_pose:
                pose_p.append({"id": tid, "joints": {}})
        gt_frames.append({"frame": frame, "people": gt_p})
        tr_frames.append({"frame": frame, "people": tr_p})
        pose_frames.append({"frame": frame, "t_ms": t, "people": pose_p})
    return ({"frames": tr_frames}, {"keyframes_only": True, "frames": gt_frames},
            {"frames": pose_frames})


def test_iou():
    assert iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert iou([0, 0, 10, 10], [20, 0, 10, 10]) == 0.0
    assert iou([0, 0, 10, 10], [5, 0, 10, 10]) == pytest.approx(1 / 3)


def test_perfect_clip_passes():
    m = evaluate(*_clip())
    assert m["pass"] and m["n_gt_people"] == 5 and m["mean_coverage"] == 1.0
    assert m["total_id_swaps"] == 0
    assert all(m["checks"].values())


def test_fewer_than_five_people_fails():
    m = evaluate(*_clip(n_people=4))
    assert not m["pass"] and not m["checks"]["enough_people"]


def test_one_missed_keyframe_in_ten_fails_coverage():
    m = evaluate(*_clip(drop=(3, 4)))  # 9/10 = 90% < 95%
    p = next(p for p in m["per_person"] if p["gt_id"] == 3)
    assert p["coverage"] == 0.9 and not m["checks"]["coverage_ge_95pct"] and not m["pass"]


def test_one_swap_allowed_on_a_short_clip():
    m = evaluate(*_clip(swap_at=(2, 5)))  # 9 s clip: max(1, 0.15 min) = 1 swap allowed
    p = next(p for p in m["per_person"] if p["gt_id"] == 2)
    assert p["id_swaps"] == 1 and p["track_ids"] == [2, 101]
    assert m["allowed_swaps"] == 1.0 and m["checks"]["swaps_le_1_per_min"] and m["pass"]


def test_two_swaps_fail_on_a_short_clip():
    tracks, gt, pose = _clip(swap_at=(2, 5))
    for f in tracks["frames"][8:]:  # person 2 switches track again
        for q in f["people"]:
            if q["id"] == 101:
                q["id"] = 202
    for f in pose["frames"][8:]:
        for q in f["people"]:
            if q["id"] == 101:
                q["id"] = 202
    m = evaluate(tracks, gt, pose)
    assert next(p for p in m["per_person"] if p["gt_id"] == 2)["id_swaps"] == 2
    assert not m["checks"]["swaps_le_1_per_min"] and not m["pass"]


def test_allowance_grows_with_clip_minutes():
    m = evaluate(*_clip(n_key=181))  # 180 s clip
    assert m["clip_min"] == 3.0 and m["allowed_swaps"] == 3.0


def test_missing_pose3d_stream_fails():
    m = evaluate(*_clip(no_pose=(4,)))
    assert not m["checks"]["pose3d_per_person"] and not m["pass"]


def test_empty_keyframes_are_unlabelled_not_failures():
    tracks, gt, pose = _clip()
    gt["frames"].insert(0, {"frame": 0, "people": []})
    gt["frames"][1]["frame"] = 0  # keep increasing-ish; first real keyframe relabelled
    m = evaluate(tracks, gt, pose)
    assert m["n_gt_people"] == 5 and m["n_keyframes"] == 50


def test_offset_boxes_below_iou_do_not_match():
    tracks, gt, pose = _clip()
    for f in tracks["frames"]:
        for p in f["people"]:
            p["bbox"] = [p["bbox"][0] + 40, 0.0, 50.0, 100.0]  # IoU 1/9 with GT
    m = evaluate(tracks, gt, pose)
    assert m["mean_coverage"] == 0.0 and not m["pass"]


def test_evaluate_files_roundtrip(tmp_path):
    tracks, gt, pose = _clip()
    for name, doc in [("tracks", tracks), ("gt", gt), ("pose", pose)]:
        (tmp_path / f"{name}.json").write_text(json.dumps(doc))
    m = evaluate_files(tmp_path / "tracks.json", tmp_path / "gt.json", tmp_path / "pose.json")
    assert m["pass"]


def test_pose3d_present_at_only_some_matched_frames_fails():
    tracks, gt, pose = _clip()
    for f in pose["frames"][5:]:  # person 3 loses their 3D stream halfway
        f["people"] = [p for p in f["people"] if p["id"] != 3]
    m = evaluate(tracks, gt, pose)
    p = next(p for p in m["per_person"] if p["gt_id"] == 3)
    assert p["pose3d_coverage"] == 0.5 and not p["has_pose3d"]
    assert not m["checks"]["pose3d_per_person"] and m["swap_rate_basis"] == "max(1, clip_min)"


def test_malformed_inputs_raise():
    tracks, gt, pose = _clip()
    gt["frames"][0]["people"].append(dict(gt["frames"][0]["people"][0]))
    with pytest.raises(ValueError, match="duplicate GT ids"):
        evaluate(tracks, gt, pose)
    tracks, gt, pose = _clip()
    tracks["frames"][0]["people"][0]["confidence"] = 1.5
    with pytest.raises(ValueError, match="confidence"):
        evaluate(tracks, gt, pose)
