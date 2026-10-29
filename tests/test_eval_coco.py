"""part2.eval_coco on hand-made photo runs (docs/specs/check-2.md AC-K13): the unchanged eval_reproj rules, each
image its own clip, rows named by image id."""
import json

import numpy as np
import pytest
from test_canonical import _body3d

from part2 import eval_coco, eval_reproj
from part2.canonical import convert
from part2.joints import CANONICAL
from part2.schema import write_json

IDS = [785 + 7 * i for i in range(20)]


def _run(scored, image_id, yaw=10, depth=4.0, frame=None, nulls=(), shift_px=0.0):
    """One photo run under scored/<image_id>/ and its label (clicks = the run's own 2D, shifted by shift_px)."""
    b = _body3d([yaw], t=(0.1, 0.3, depth))
    n = image_id if frame is None else frame
    b["frames"][0]["frame"] = n
    pose3d, camera = convert(b)
    out = scored / str(image_id)
    out.mkdir(parents=True)
    write_json(out / "pose3d.json", pose3d)
    write_json(out / "camera.json", camera)
    kp2d = b["frames"][0]["people"][0]["kp2d"]
    joints = {j: None if j in nulls else (np.asarray(kp2d[j]) + [shift_px, 0]).tolist() for j in CANONICAL}
    return {"frame": image_id, "file_name": f"{image_id:012d}.jpg", "joints": joints}


def _set(tmp_path, ids=IDS, **kw):
    scored = tmp_path / "coco-single"
    scored.mkdir()
    return scored, {"frames": [_run(scored, i, **kw) for i in ids]}


def test_perfect_runs_pass_with_eval_reproj_threshold_and_rule(tmp_path):
    scored, labels = _set(tmp_path)
    m = eval_coco.evaluate(scored, labels)
    assert m["pass"] and m["n_frames"] == 20 and m["n_failed_frames"] == 0 and m["max_pct"] < 0.1
    assert m["threshold_pct"] == eval_reproj.THRESHOLD * 100 == 5.0 and m["rule"] == "every_frame"
    assert m["checks"] == {"enough_frames": True, "within_threshold": True}  # no side-view check (#337)
    assert [r["frame"] for r in m["per_frame"]] == IDS


def test_body_height_is_each_images_own_nose_to_ankle_midpoint(tmp_path):
    scored = tmp_path / "s"
    scored.mkdir()
    near = _run(scored, 1, depth=4.0, shift_px=6.0)
    far = _run(scored, 2, depth=8.0, shift_px=6.0)
    rows = {r["frame"]: r for r in eval_coco.evaluate(scored, {"frames": [near, far]}, min_frames=2)["per_frame"]}
    for lf in (near, far):
        clicks = {j: np.asarray(uv) for j, uv in lf["joints"].items()}
        own = eval_reproj.body_height_px(clicks)
        assert rows[lf["frame"]]["height_px"] == pytest.approx(own, abs=0.05)
        assert rows[lf["frame"]]["error_pct"] == pytest.approx(600 / own, abs=1e-3)
    assert rows[2]["height_px"] < 0.6 * rows[1]["height_px"]  # never the clip max over images


def test_one_bad_image_fails_every_frame_but_passes_the_mean_rule(tmp_path):
    scored = tmp_path / "s"
    scored.mkdir()
    labels = {"frames": [_run(scored, i, shift_px=60.0 if i == IDS[7] else 0.0) for i in IDS]}
    m = eval_coco.evaluate(scored, labels)
    assert not m["pass"] and m["n_failed_frames"] == 1 and m["worst_frame"] == IDS[7]
    assert not m["checks"]["within_threshold"]
    assert eval_coco.evaluate(scored, labels, rule="mean")["checks"]["within_threshold"]
    with pytest.raises(ValueError, match="unknown rule"):
        eval_coco.evaluate(scored, labels, rule="median")


def test_null_joints_are_not_scored(tmp_path):
    scored, labels = _set(tmp_path, ids=[5], nulls=("left_ear", "right_wrist"))
    labels["frames"][0]["joints"]["left_knee"] = None
    row = eval_coco.evaluate(scored, labels, min_frames=1)["per_frame"][0]
    assert row["n_joints"] == 14 and row["ok"]


def test_run_frame_number_need_not_be_the_image_id(tmp_path):
    scored, labels = _set(tmp_path, ids=[42], frame=0)
    row = eval_coco.evaluate(scored, labels, min_frames=1)["per_frame"][0]
    assert row["frame"] == 42 and row["ok"] and row["error_pct"] < 0.1


def test_missing_empty_and_multi_frame_runs_fail(tmp_path):
    scored, labels = _set(tmp_path, ids=[1, 2, 3])
    for n in ("pose3d.json", "camera.json"):
        (scored / "1" / n).unlink()
    empty = json.loads((scored / "2" / "pose3d.json").read_text())
    empty["frames"] = []
    write_json(scored / "2" / "pose3d.json", empty)
    two = json.loads((scored / "3" / "pose3d.json").read_text())
    two["frames"] = two["frames"] * 2
    write_json(scored / "3" / "pose3d.json", two)
    rows = {r["frame"]: r for r in eval_coco.evaluate(scored, labels)["per_frame"]}
    assert "missing output" in rows[1]["note"] and "run make outputs" in rows[1]["note"]
    assert "no prediction" in rows[2]["note"]
    assert "not a photo run: 2 frames" in rows[3]["note"]
    assert not any(r["ok"] for r in rows.values())


def test_too_few_images_fail_enough_frames(tmp_path):
    scored, labels = _set(tmp_path, ids=IDS[:19])
    m = eval_coco.evaluate(scored, labels)
    assert m["checks"] == {"enough_frames": False, "within_threshold": True} and not m["pass"]


def test_labels_are_validated(tmp_path):
    scored, labels = _set(tmp_path, ids=[1])
    labels["frames"][0]["joints"]["chin"] = [1, 2]
    with pytest.raises(ValueError, match="unknown joints"):
        eval_coco.evaluate(scored, labels)


def test_block_drops_rows_and_fails_on_a_missing_dir(tmp_path):
    scored, labels = _set(tmp_path)
    path = tmp_path / "labels_2d.json"
    write_json(path, labels)
    m = eval_coco.block(scored, path)
    assert m["pass"] and "per_frame" not in m and m["body_height"] == eval_coco.BODY_HEIGHT
    gone = eval_coco.block(tmp_path / "nope", path)
    assert gone == {"pass": False, "status": f"missing output {tmp_path / 'nope'}; run make outputs"}


def test_cli_prints_json_and_exits_by_the_rule(tmp_path, capsys):
    scored, labels = _set(tmp_path)
    path = tmp_path / "labels_2d.json"
    write_json(path, labels)
    assert eval_coco.main(["--scored", str(scored), "--labels", str(path)]) == 0
    assert "per_frame" not in json.loads(capsys.readouterr().out)
    assert eval_coco.main(["--scored", str(scored), "--labels", str(path), "--per-frame"]) == 0
    assert len(json.loads(capsys.readouterr().out)["per_frame"]) == 20
    assert eval_coco.main(["--scored", str(tmp_path / "nope"), "--labels", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["pass"] is False


def test_default_paths_name_the_committed_set():
    assert eval_coco.LABELS.relative_to(eval_coco.ROOT).as_posix() == "fixtures/input/coco/labels_2d.json"
    assert eval_coco.SCORED.relative_to(eval_coco.ROOT).as_posix() == "fixtures/output/scored/coco-single"
